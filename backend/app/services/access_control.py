from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.custom_scope import CustomScopeItem, CustomScopeSet
from app.models.device_group import DeviceGroup
from app.models.project import Project
from app.models.site import Site
from app.models.tenant import Tenant, TenantSiteBinding, UserTenantRole
from app.models.user import Role, User, UserDataScope
from app.schemas.tenant import UserTenantRoleView
from app.schemas.user import (
    CoreRoleOption,
    PermissionOption,
    PermissionTemplateOption,
    UserDataScopeView,
)

HQ_TENANT_CODE = "HQ-GROUP"
DEFAULT_SUB_TENANT_CODE = "SUB-A"

CORE_ROLE_PLATFORM = "platform_admin"
CORE_ROLE_COMPANY = "company_admin"
CORE_ROLE_EMPLOYEE = "employee"

CORE_ROLE_DEFINITIONS: list[CoreRoleOption] = [
    CoreRoleOption(key=CORE_ROLE_PLATFORM, label="平台管理员", description="负责创建公司和公司管理员"),
    CoreRoleOption(key=CORE_ROLE_COMPANY, label="公司管理员", description="负责管理本公司的员工和授权"),
    CoreRoleOption(key=CORE_ROLE_EMPLOYEE, label="普通员工", description="只访问被授权的功能和数据"),
]
CORE_ROLE_SET = {item.key for item in CORE_ROLE_DEFINITIONS}

PERMISSION_DEFINITIONS: list[PermissionOption] = [
    PermissionOption(key="dashboard.view", label="查看监控总览", description="查看平台总览和核心指标"),
    PermissionOption(key="realtime.view", label="查看实时监控", description="查看实时监控页面和趋势曲线"),
    PermissionOption(key="history.view", label="查看历史数据", description="查看历史曲线和历史记录"),
    PermissionOption(key="alarm.view", label="查看告警", description="查看告警中心和告警详情"),
    PermissionOption(key="alarm.handle", label="处理告警", description="确认和关闭告警"),
    PermissionOption(key="site.view", label="查看站点", description="查看站点和授权范围选项"),
    PermissionOption(key="site.manage", label="管理站点", description="创建和编辑站点"),
    PermissionOption(key="rule.view", label="查看规则", description="查看告警规则和策略"),
    PermissionOption(key="rule.manage", label="管理规则", description="维护告警规则和策略"),
    PermissionOption(key="notify.view", label="查看通知", description="查看通知配置"),
    PermissionOption(key="notify.manage", label="管理通知", description="维护通知通道、策略和值班配置"),
    PermissionOption(key="report.export", label="导出报表", description="导出报表和查询结果"),
    PermissionOption(key="user.manage_company", label="管理员工", description="管理本公司员工账号与授权"),
]
ASSIGNABLE_PERMISSION_KEYS = {item.key for item in PERMISSION_DEFINITIONS}
PERMISSION_KEY_SET = set(ASSIGNABLE_PERMISSION_KEYS)
PERMISSION_KEY_SET.update(
    {
        "alarm.ack",
        "alarm.close",
        "site.create",
        "site.update",
        "alarm_rule.template.view",
        "alarm_rule.template.manage",
        "alarm_rule.tenant.view",
        "alarm_rule.tenant.manage",
        "notify.channel.view",
        "notify.channel.manage",
        "notify.policy.view",
        "notify.policy.manage",
        "notify.receiver.view",
        "notify.receiver.manage",
        "notify.group.view",
        "notify.group.manage",
        "notify.rule.view",
        "notify.rule.manage",
        "notify.oncall.view",
        "notify.oncall.manage",
        "notify.push_log.view",
        "notify.push_log.retry",
        "user.view",
        "user.manage",
        "audit.view",
        "tenant.manage",
    }
)

SCOPE_TYPE_DEFINITIONS: list[PermissionOption] = [
    PermissionOption(key="tenant", label="本公司全部", description="可访问当前公司全部数据"),
    PermissionOption(key="site", label="指定站点", description="仅访问指定站点数据"),
    PermissionOption(key="device_group", label="指定设备组", description="仅访问指定设备组数据"),
]
SCOPE_TYPE_SET = {"all", "tenant", "site", "device_group", "project", "region", "custom"}

PERMISSION_TEMPLATE_DEFINITIONS: list[PermissionTemplateOption] = [
    PermissionTemplateOption(
        key="monitor_viewer",
        label="监控查看员",
        description="用于只读查看实时、历史和告警信息",
        permission_keys=["dashboard.view", "realtime.view", "history.view", "alarm.view", "site.view"],
    ),
    PermissionTemplateOption(
        key="alarm_operator",
        label="告警处理员",
        description="在监控查看基础上增加告警处理能力",
        permission_keys=["dashboard.view", "realtime.view", "history.view", "alarm.view", "alarm.handle", "site.view"],
    ),
    PermissionTemplateOption(
        key="rule_admin",
        label="规则管理员",
        description="负责维护规则和策略",
        permission_keys=["site.view", "rule.view", "rule.manage"],
    ),
    PermissionTemplateOption(
        key="notify_admin",
        label="通知管理员",
        description="负责维护通知配置和值班策略",
        permission_keys=["site.view", "notify.view", "notify.manage"],
    ),
    PermissionTemplateOption(
        key="ops_generalist",
        label="综合运维员",
        description="兼顾监控查看、告警处理和站点维护",
        permission_keys=[
            "dashboard.view",
            "realtime.view",
            "history.view",
            "alarm.view",
            "alarm.handle",
            "site.view",
            "site.manage",
            "report.export",
        ],
    ),
]
PERMISSION_TEMPLATE_MAP = {item.key: item for item in PERMISSION_TEMPLATE_DEFINITIONS}

ROLE_CORE_ROLE_ALIASES: dict[str, str] = {
    CORE_ROLE_PLATFORM: CORE_ROLE_PLATFORM,
    CORE_ROLE_COMPANY: CORE_ROLE_COMPANY,
    CORE_ROLE_EMPLOYEE: CORE_ROLE_EMPLOYEE,
    "admin": CORE_ROLE_PLATFORM,
    "hq_noc": CORE_ROLE_PLATFORM,
    "sub_noc": CORE_ROLE_COMPANY,
    "operator": CORE_ROLE_EMPLOYEE,
}

BUILTIN_ROLE_DEFAULT_PERMISSIONS: dict[str, set[str]] = {
    CORE_ROLE_PLATFORM: {
        "dashboard.view",
        "realtime.view",
        "history.view",
        "alarm.view",
        "site.view",
        "rule.view",
        "notify.view",
        "report.export",
        "tenant.manage",
    },
    CORE_ROLE_COMPANY: set(),
    CORE_ROLE_EMPLOYEE: set(),
    "admin": {"tenant.manage"},
    "hq_noc": {"tenant.manage"},
    "sub_noc": {"user.manage_company", "site.view"},
    "operator": set(),
}

PERMISSION_ALIASES: dict[str, set[str]] = {
    "alarm.handle": {"alarm.ack", "alarm.close"},
    "alarm.ack": {"alarm.handle"},
    "alarm.close": {"alarm.handle"},
    "site.manage": {"site.create", "site.update"},
    "site.create": {"site.manage"},
    "site.update": {"site.manage"},
    "rule.view": {"alarm_rule.template.view", "alarm_rule.tenant.view"},
    "rule.manage": {
        "rule.view",
        "alarm_rule.template.view",
        "alarm_rule.template.manage",
        "alarm_rule.tenant.view",
        "alarm_rule.tenant.manage",
    },
    "alarm_rule.template.view": {"rule.view"},
    "alarm_rule.tenant.view": {"rule.view"},
    "alarm_rule.template.manage": {"rule.manage", "rule.view"},
    "alarm_rule.tenant.manage": {"rule.manage", "rule.view"},
    "notify.view": {
        "notify.channel.view",
        "notify.policy.view",
        "notify.receiver.view",
        "notify.group.view",
        "notify.rule.view",
        "notify.oncall.view",
        "notify.push_log.view",
    },
    "notify.manage": {
        "notify.view",
        "notify.channel.view",
        "notify.channel.manage",
        "notify.policy.view",
        "notify.policy.manage",
        "notify.receiver.view",
        "notify.receiver.manage",
        "notify.group.view",
        "notify.group.manage",
        "notify.rule.view",
        "notify.rule.manage",
        "notify.oncall.view",
        "notify.oncall.manage",
        "notify.push_log.view",
        "notify.push_log.retry",
    },
    "notify.channel.view": {"notify.view"},
    "notify.policy.view": {"notify.view"},
    "notify.receiver.view": {"notify.view"},
    "notify.group.view": {"notify.view"},
    "notify.rule.view": {"notify.view"},
    "notify.oncall.view": {"notify.view"},
    "notify.push_log.view": {"notify.view"},
    "notify.channel.manage": {"notify.manage", "notify.view"},
    "notify.policy.manage": {"notify.manage", "notify.view"},
    "notify.receiver.manage": {"notify.manage", "notify.view"},
    "notify.group.manage": {"notify.manage", "notify.view"},
    "notify.rule.manage": {"notify.manage", "notify.view"},
    "notify.oncall.manage": {"notify.manage", "notify.view"},
    "notify.push_log.retry": {"notify.manage", "notify.view"},
    "user.manage_company": {"user.view", "user.manage", "audit.view"},
    "user.view": {"user.manage_company"},
    "user.manage": {"user.manage_company"},
}


@dataclass
class ScopeSet:
    has_all: bool = False
    tenant_ids: set[int] = field(default_factory=set)
    tenant_codes: set[str] = field(default_factory=set)
    project_ids: set[int] = field(default_factory=set)
    project_codes: set[str] = field(default_factory=set)
    site_ids: set[int] = field(default_factory=set)
    site_codes: set[str] = field(default_factory=set)
    device_group_ids: set[int] = field(default_factory=set)
    custom_scope_set_ids: set[int] = field(default_factory=set)
    regions: set[str] = field(default_factory=set)


@dataclass
class AccessContext:
    user_id: int
    username: str
    core_role: str
    role_names: set[str]
    permissions: set[str]
    tenant_roles: list[UserTenantRoleView]
    data_scopes: list[UserDataScopeView]
    role_bindings: list[dict]
    scopes: ScopeSet

    def has_permission(self, permission_key: str) -> bool:
        return permission_key in self.permissions

    @property
    def tenant_ids(self) -> set[int]:
        return self.scopes.tenant_ids

    @property
    def tenant_codes(self) -> set[str]:
        return self.scopes.tenant_codes

    @property
    def project_ids(self) -> set[int]:
        return self.scopes.project_ids

    @property
    def project_codes(self) -> set[str]:
        return self.scopes.project_codes

    @property
    def site_ids(self) -> set[int]:
        return self.scopes.site_ids

    @property
    def site_codes(self) -> set[str]:
        return self.scopes.site_codes

    @property
    def device_group_ids(self) -> set[int]:
        return self.scopes.device_group_ids

    @property
    def custom_scope_set_ids(self) -> set[int]:
        return self.scopes.custom_scope_set_ids

    @property
    def regions(self) -> set[str]:
        return self.scopes.regions

    @property
    def is_platform_admin(self) -> bool:
        return self.core_role == CORE_ROLE_PLATFORM

    @property
    def is_company_admin(self) -> bool:
        return self.core_role == CORE_ROLE_COMPANY

    @property
    def is_admin(self) -> bool:
        return self.is_platform_admin or self.is_company_admin

    @property
    def can_manage_users(self) -> bool:
        return self.is_admin

    @property
    def can_global_read(self) -> bool:
        return self.is_platform_admin or self.scopes.has_all

    @property
    def can_manage_templates(self) -> bool:
        return self.has_permission("rule.manage")

    @property
    def can_view_tenant_strategy(self) -> bool:
        return self.has_permission("rule.view") or self.has_permission("rule.manage")

    @property
    def can_edit_tenant_strategy(self) -> bool:
        return self.has_permission("rule.manage")

    @property
    def can_manage_tenant_assets(self) -> bool:
        return self.has_permission("site.manage") or self.has_permission("site.create") or self.has_permission("site.update")


def get_core_role_options() -> list[CoreRoleOption]:
    return [CoreRoleOption(**item.model_dump()) for item in CORE_ROLE_DEFINITIONS]


def get_permission_options() -> list[PermissionOption]:
    return [PermissionOption(**item.model_dump()) for item in PERMISSION_DEFINITIONS]


def get_scope_type_options() -> list[PermissionOption]:
    return [PermissionOption(**item.model_dump()) for item in SCOPE_TYPE_DEFINITIONS]


def get_permission_templates() -> list[PermissionTemplateOption]:
    return [PermissionTemplateOption(**item.model_dump()) for item in PERMISSION_TEMPLATE_DEFINITIONS]


def normalize_assignable_permissions(permission_keys: list[str] | set[str]) -> list[str]:
    keys = sorted({str(item or "").strip() for item in permission_keys if str(item or "").strip()})
    invalid = [item for item in keys if item not in ASSIGNABLE_PERMISSION_KEYS]
    if invalid:
        raise ValueError(f"存在未定义的功能权限：{'、'.join(invalid)}")
    return keys


def expand_permissions(raw_permissions: set[str] | list[str]) -> set[str]:
    expanded = {item for item in raw_permissions if item}
    changed = True
    while changed:
        changed = False
        for key in list(expanded):
            additions = PERMISSION_ALIASES.get(key, set())
            if not additions.issubset(expanded):
                expanded.update(additions)
                changed = True
    return expanded


def simplify_permissions(raw_permissions: set[str] | list[str]) -> list[str]:
    expanded = expand_permissions(raw_permissions)
    return sorted(key for key in ASSIGNABLE_PERMISSION_KEYS if key in expanded)


def resolve_template_permissions(template_key: str | None) -> list[str]:
    if not template_key:
        return []
    template = PERMISSION_TEMPLATE_MAP.get(template_key)
    if template is None:
        raise ValueError("权限模板不存在")
    return list(template.permission_keys)


def match_template_key(raw_permissions: set[str] | list[str]) -> str | None:
    simplified = simplify_permissions(raw_permissions)
    for item in PERMISSION_TEMPLATE_DEFINITIONS:
        if simplified == sorted(item.permission_keys):
            return item.key
    return None


def get_user_core_role(role_names: set[str] | list[str]) -> str:
    names = {str(item or "").strip() for item in role_names if str(item or "").strip()}
    if any(ROLE_CORE_ROLE_ALIASES.get(name) == CORE_ROLE_PLATFORM for name in names):
        return CORE_ROLE_PLATFORM
    if any(ROLE_CORE_ROLE_ALIASES.get(name) == CORE_ROLE_COMPANY for name in names):
        return CORE_ROLE_COMPANY
    return CORE_ROLE_EMPLOYEE


def get_role_permissions(role: Role) -> set[str]:
    explicit = {item.permission_key for item in getattr(role, "permissions", []) if item.permission_key}
    if explicit:
        return expand_permissions(explicit)
    return expand_permissions(BUILTIN_ROLE_DEFAULT_PERMISSIONS.get(role.name, set()))


def get_default_permissions_for_core_role(core_role: str) -> list[str]:
    if core_role == CORE_ROLE_PLATFORM:
        return [
            "dashboard.view",
            "realtime.view",
            "history.view",
            "alarm.view",
            "site.view",
            "rule.view",
            "notify.view",
            "report.export",
        ]
    if core_role == CORE_ROLE_COMPANY:
        return ["site.view", "user.manage_company"]
    return []


def _build_role_bindings(
    *,
    user_roles: list[Role],
    tenant_roles: list[UserTenantRoleView],
    data_scopes: list[UserDataScopeView],
) -> list[dict]:
    bindings: list[dict] = []
    scopes_payload = [
        {
            "scope_type": item.scope_type,
            "scope_value": item.scope_value,
            "scope_name": item.scope_name,
        }
        for item in data_scopes
    ]
    tenant_role_map: dict[str, list[dict]] = {}
    for item in tenant_roles:
        tenant_role_map.setdefault(item.role_name, []).append(
            {
                "tenant_code": item.tenant_code,
                "tenant_name": item.tenant_name,
                "tenant_type": item.tenant_type,
                "scope_level": item.scope_level,
            }
        )

    for role in sorted(user_roles, key=lambda item: item.name):
        bindings.append(
            {
                "role_name": role.name,
                "permissions": simplify_permissions(get_role_permissions(role)),
                "tenant_bindings": tenant_role_map.get(role.name, []),
                "scopes": scopes_payload,
            }
        )
    return bindings


def build_access_context(db: Session, user: User) -> AccessContext:
    user_roles = sorted(user.roles, key=lambda item: item.name)
    role_names = {item.name for item in user_roles}
    core_role = get_user_core_role(role_names)
    permissions: set[str] = set()
    for role in user_roles:
        permissions.update(get_role_permissions(role))

    scope_set = ScopeSet()
    tenant_roles: list[UserTenantRoleView] = []
    data_scopes: list[UserDataScopeView] = []

    tenant_role_rows = list(
        db.execute(
            select(UserTenantRole).where(UserTenantRole.user_id == user.id).order_by(UserTenantRole.id.asc())
        ).scalars()
    )
    for row in tenant_role_rows:
        tenant_roles.append(
            UserTenantRoleView(
                tenant_code=row.tenant.code,
                tenant_name=row.tenant.name,
                tenant_type=row.tenant.tenant_type,
                role_name=row.role.name,
                scope_level=row.scope_level,
            )
        )
        scope_set.tenant_ids.add(row.tenant_id)
        scope_set.tenant_codes.add(row.tenant.code)

    scope_rows = list(
        db.execute(select(UserDataScope).where(UserDataScope.user_id == user.id).order_by(UserDataScope.id.asc())).scalars()
    )
    if not scope_rows and core_role == CORE_ROLE_PLATFORM:
        scope_rows = [UserDataScope(user_id=user.id, scope_type="all", scope_value="*", scope_name="全部公司")]

    for row in scope_rows:
        scope_type = row.scope_type
        scope_value = row.scope_value
        scope_name = row.scope_name

        if scope_type == "all":
            scope_set.has_all = True
            scope_value = "*"
            scope_name = scope_name or "全部公司"
        elif scope_type == "tenant":
            tenant = db.scalar(select(Tenant).where(Tenant.code == scope_value))
            if tenant is not None:
                scope_set.tenant_ids.add(tenant.id)
                scope_set.tenant_codes.add(tenant.code)
                scope_name = scope_name or tenant.name
        elif scope_type == "project":
            project = db.scalar(select(Project).where(Project.code == scope_value))
            if project is not None:
                scope_set.project_ids.add(project.id)
                scope_set.project_codes.add(project.code)
                scope_set.tenant_ids.add(project.tenant_id)
                tenant = db.get(Tenant, project.tenant_id)
                if tenant is not None:
                    scope_set.tenant_codes.add(tenant.code)
                scope_name = scope_name or project.name
        elif scope_type == "site":
            site = db.scalar(select(Site).where(Site.code == scope_value))
            if site is not None:
                scope_set.site_ids.add(site.id)
                scope_set.site_codes.add(site.code)
                scope_name = scope_name or site.name
                tenant = get_tenant_for_site(db, site.id)
                if tenant is not None:
                    scope_set.tenant_ids.add(tenant.id)
                    scope_set.tenant_codes.add(tenant.code)
        elif scope_type == "device_group":
            device_group = db.scalar(select(DeviceGroup).where(DeviceGroup.code == scope_value))
            if device_group is not None:
                scope_set.device_group_ids.add(device_group.id)
                scope_set.tenant_ids.add(device_group.tenant_id)
                tenant = db.get(Tenant, device_group.tenant_id)
                if tenant is not None:
                    scope_set.tenant_codes.add(tenant.code)
                scope_name = scope_name or device_group.name
        elif scope_type == "custom":
            try:
                custom_scope_id = int(scope_value)
            except (TypeError, ValueError):
                custom_scope_id = None
            if custom_scope_id:
                custom_scope = db.scalar(select(CustomScopeSet).where(CustomScopeSet.id == custom_scope_id))
                if custom_scope is not None:
                    scope_set.custom_scope_set_ids.add(custom_scope.id)
                    scope_set.tenant_ids.add(custom_scope.tenant_id)
                    tenant = db.get(Tenant, custom_scope.tenant_id)
                    if tenant is not None:
                        scope_set.tenant_codes.add(tenant.code)
                    scope_name = scope_name or custom_scope.name
        elif scope_type == "region":
            region = str(scope_value or "").strip()
            if region:
                scope_set.regions.add(region)
                scope_name = scope_name or region

        data_scopes.append(
            UserDataScopeView(
                scope_type=scope_type,
                scope_value=scope_value,
                scope_name=scope_name,
            )
        )

    return AccessContext(
        user_id=user.id,
        username=user.username,
        core_role=core_role,
        role_names=role_names,
        permissions=permissions,
        tenant_roles=tenant_roles,
        data_scopes=data_scopes,
        role_bindings=_build_role_bindings(user_roles=user_roles, tenant_roles=tenant_roles, data_scopes=data_scopes),
        scopes=scope_set,
    )


def get_accessible_site_ids(db: Session, access: AccessContext) -> set[int] | None:
    if access.can_global_read:
        return None

    site_ids = set(access.site_ids)
    if access.project_ids:
        project_site_ids = db.scalars(
            select(DeviceGroup.site_id).where(DeviceGroup.project_id.in_(access.project_ids), DeviceGroup.site_id.is_not(None))
        ).all()
        site_ids.update(project_site_ids)
    if access.tenant_ids:
        tenant_site_ids = db.scalars(
            select(TenantSiteBinding.site_id).where(TenantSiteBinding.tenant_id.in_(access.tenant_ids))
        ).all()
        site_ids.update(tenant_site_ids)
    if access.device_group_ids:
        device_group_site_ids = db.scalars(
            select(DeviceGroup.site_id).where(DeviceGroup.id.in_(access.device_group_ids), DeviceGroup.site_id.is_not(None))
        ).all()
        site_ids.update(device_group_site_ids)
    if access.custom_scope_set_ids:
        custom_site_ids = db.scalars(
            select(CustomScopeItem.resource_id).where(CustomScopeItem.scope_set_id.in_(access.custom_scope_set_ids))
        ).all()
        site_ids.update(custom_site_ids)
    if access.regions:
        region_site_ids = db.scalars(select(Site.id).where(Site.region.in_(access.regions))).all()
        site_ids.update(region_site_ids)
    return site_ids


def find_tenant_by_code(db: Session, tenant_code: str) -> Tenant | None:
    code = tenant_code.strip()
    if not code:
        return None
    return db.scalar(select(Tenant).where(Tenant.code == code))


def ensure_site_tenant_binding(db: Session, *, site_id: int, tenant_id: int):
    exists = db.scalar(select(TenantSiteBinding).where(TenantSiteBinding.site_id == site_id))
    if exists is not None:
        if exists.tenant_id != tenant_id:
            exists.tenant_id = tenant_id
        return
    db.add(
        TenantSiteBinding(
            tenant_id=tenant_id,
            site_id=site_id,
            created_at=datetime.now(timezone.utc),
        )
    )


def get_default_sub_tenant(db: Session) -> Tenant:
    tenant = db.scalar(select(Tenant).where(Tenant.code == DEFAULT_SUB_TENANT_CODE))
    if tenant:
        return tenant
    tenant = db.scalar(select(Tenant).where(Tenant.code == HQ_TENANT_CODE))
    if tenant:
        return tenant
    tenant = db.scalar(select(Tenant).order_by(Tenant.id.asc()))
    if tenant:
        return tenant
    raise ValueError("未找到可用租户")


def get_site_tenant_code_map(db: Session, site_ids: list[int]) -> dict[int, str]:
    if not site_ids:
        return {}
    rows = db.execute(
        select(TenantSiteBinding.site_id, Tenant.code)
        .join(Tenant, Tenant.id == TenantSiteBinding.tenant_id)
        .where(TenantSiteBinding.site_id.in_(site_ids))
    ).all()
    return {site_id: tenant_code for site_id, tenant_code in rows}


def get_tenant_for_site(db: Session, site_id: int) -> Tenant | None:
    binding = db.scalar(select(TenantSiteBinding).where(TenantSiteBinding.site_id == site_id))
    if binding is None:
        return None
    return db.get(Tenant, binding.tenant_id)


def get_tenant_for_site_code(db: Session, site_code: str) -> Tenant | None:
    site = db.scalar(select(Site).where(Site.code == site_code))
    if site is None:
        return None
    return get_tenant_for_site(db, site.id)
