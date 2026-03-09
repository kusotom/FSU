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
from app.schemas.user import PermissionOption, UserDataScopeView

HQ_TENANT_CODE = "HQ-GROUP"
DEFAULT_SUB_TENANT_CODE = "SUB-A"

PERMISSION_DEFINITIONS: list[PermissionOption] = [
    PermissionOption(key="dashboard.view", label="查看监控大盘", description="查看平台总览和核心指标"),
    PermissionOption(key="realtime.view", label="查看实时监控", description="查看实时监控页面与趋势曲线"),
    PermissionOption(key="realtime.important.manage", label="配置关键监控项", description="维护实时监控关键项"),
    PermissionOption(key="alarm.view", label="查看告警详情", description="查看告警中心与告警详情"),
    PermissionOption(key="alarm.ack", label="确认告警", description="对活动告警执行确认"),
    PermissionOption(key="alarm.close", label="关闭告警", description="对告警执行关闭"),
    PermissionOption(key="history.view", label="查看历史数据", description="查看历史曲线和记录"),
    PermissionOption(key="report.export", label="导出报表", description="导出报表和查询结果"),
    PermissionOption(key="device.command.send", label="下发设备指令", description="向设备发送控制指令"),
    PermissionOption(key="site.view", label="查看站点", description="查看站点列表与站点详情"),
    PermissionOption(key="site.create", label="新建站点", description="创建新站点"),
    PermissionOption(key="site.update", label="编辑站点", description="编辑站点基础信息"),
    PermissionOption(key="alarm_rule.template.view", label="查看总部规则模板", description="查看总部级规则模板"),
    PermissionOption(key="alarm_rule.template.manage", label="管理总部规则模板", description="创建和维护总部级规则模板"),
    PermissionOption(key="alarm_rule.tenant.view", label="查看租户监控策略", description="查看租户级监控策略"),
    PermissionOption(key="alarm_rule.tenant.manage", label="管理租户监控策略", description="创建和维护租户级监控策略"),
    PermissionOption(key="notify.channel.view", label="查看通知通道", description="查看通知通道配置"),
    PermissionOption(key="notify.channel.manage", label="管理通知通道", description="创建、测试、编辑、删除通知通道"),
    PermissionOption(key="notify.policy.view", label="查看通知策略", description="查看通知策略配置"),
    PermissionOption(key="notify.policy.manage", label="管理通知策略", description="创建、编辑、删除通知策略"),
    PermissionOption(key="notify.receiver.view", label="查看接收人", description="查看公司级通知接收人"),
    PermissionOption(key="notify.receiver.manage", label="管理接收人", description="创建、编辑、删除公司级通知接收人"),
    PermissionOption(key="notify.group.view", label="查看通知组", description="查看公司级通知组"),
    PermissionOption(key="notify.group.manage", label="管理通知组", description="创建、编辑、删除公司级通知组"),
    PermissionOption(key="notify.rule.view", label="查看推送规则", description="查看公司级告警推送规则"),
    PermissionOption(key="notify.rule.manage", label="管理推送规则", description="创建、编辑、删除公司级告警推送规则"),
    PermissionOption(key="user.view", label="查看账号", description="查看用户、角色与数据范围"),
    PermissionOption(key="user.manage", label="管理账号", description="管理用户、角色与数据范围"),
    PermissionOption(key="audit.view", label="查看操作记录", description="查看公司级操作审计记录"),
]
PERMISSION_KEY_SET = {item.key for item in PERMISSION_DEFINITIONS}

SCOPE_TYPE_DEFINITIONS: list[PermissionOption] = [
    PermissionOption(key="all", label="全部数据", description="可查看所有租户、站点和设备数据"),
    PermissionOption(key="tenant", label="按公司", description="按公司控制可见数据"),
    PermissionOption(key="project", label="按项目", description="按项目控制可见数据"),
    PermissionOption(key="site", label="按站点", description="只允许查看指定站点"),
    PermissionOption(key="device_group", label="按设备组", description="只允许查看指定设备组"),
    PermissionOption(key="region", label="按区域", description="按区域控制站点可见范围"),
    PermissionOption(key="custom", label="按自定义范围", description="按自定义站点集合控制可见范围"),
]
SCOPE_TYPE_SET = {item.key for item in SCOPE_TYPE_DEFINITIONS}

BUILTIN_ROLE_DEFAULT_PERMISSIONS: dict[str, set[str]] = {
    "admin": {item.key for item in PERMISSION_DEFINITIONS},
    "operator": {"dashboard.view", "realtime.view", "alarm.view", "history.view", "site.view"},
    "hq_noc": {
        "dashboard.view",
        "realtime.view",
        "alarm.view",
        "alarm.ack",
        "alarm.close",
        "history.view",
        "site.view",
        "alarm_rule.template.manage",
        "alarm_rule.template.view",
        "notify.channel.view",
        "notify.channel.manage",
        "notify.policy.view",
        "notify.policy.manage",
        "notify.receiver.view",
        "notify.group.view",
        "notify.rule.view",
        "audit.view",
    },
    "sub_noc": {
        "dashboard.view",
        "realtime.view",
        "alarm.view",
        "alarm.ack",
        "alarm.close",
        "history.view",
        "site.view",
        "site.create",
        "site.update",
        "alarm_rule.tenant.manage",
        "alarm_rule.tenant.view",
        "notify.channel.view",
        "notify.policy.view",
        "notify.receiver.view",
        "notify.receiver.manage",
        "notify.group.view",
        "notify.group.manage",
        "notify.rule.view",
        "notify.rule.manage",
        "user.view",
        "user.manage",
        "audit.view",
    },
}

PERMISSION_ALIASES: dict[str, set[str]] = {
    "alarm.view": {"alarm.ack", "alarm.close"},
    "site.manage": {"site.create", "site.update"},
    "user.view": {"audit.view"},
    "notify.view": {"notify.channel.view", "notify.policy.view"},
    "notify.manage": {
        "notify.channel.view",
        "notify.channel.manage",
        "notify.policy.view",
        "notify.policy.manage",
        "notify.receiver.view",
        "notify.group.view",
        "notify.rule.view",
    },
    "notify.policy.view": {"notify.rule.view"},
    "notify.policy.manage": {
        "notify.rule.view",
        "notify.rule.manage",
        "notify.receiver.view",
        "notify.group.view",
    },
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
    def is_admin(self) -> bool:
        return self.has_permission("user.manage")

    @property
    def is_hq_noc(self) -> bool:
        return self.has_permission("alarm_rule.template.manage") or self.has_permission("alarm_rule.template.view")

    @property
    def is_sub_noc(self) -> bool:
        return self.has_permission("alarm_rule.tenant.manage") or self.has_permission("alarm_rule.tenant.view")

    @property
    def can_global_read(self) -> bool:
        return self.scopes.has_all

    @property
    def can_manage_templates(self) -> bool:
        return self.has_permission("alarm_rule.template.manage")

    @property
    def can_view_tenant_strategy(self) -> bool:
        return (
            self.has_permission("alarm_rule.template.manage")
            or self.has_permission("alarm_rule.template.view")
            or self.has_permission("alarm_rule.tenant.manage")
            or self.has_permission("alarm_rule.tenant.view")
        )

    @property
    def can_edit_tenant_strategy(self) -> bool:
        return self.has_permission("alarm_rule.template.manage") or self.has_permission("alarm_rule.tenant.manage")

    @property
    def can_manage_tenant_assets(self) -> bool:
        return self.has_permission("site.create") or self.has_permission("site.update")


def get_permission_options() -> list[PermissionOption]:
    return [PermissionOption(**item.model_dump()) for item in PERMISSION_DEFINITIONS]


def get_scope_type_options() -> list[PermissionOption]:
    return [PermissionOption(**item.model_dump()) for item in SCOPE_TYPE_DEFINITIONS]


def expand_permissions(raw_permissions: set[str] | list[str]) -> set[str]:
    expanded = {item for item in raw_permissions if item}
    for key in list(expanded):
        expanded.update(PERMISSION_ALIASES.get(key, set()))
    return expanded


def get_role_permissions(role: Role) -> set[str]:
    explicit = {item.permission_key for item in getattr(role, "permissions", []) if item.permission_key}
    if explicit:
        return expand_permissions(explicit)
    return expand_permissions(BUILTIN_ROLE_DEFAULT_PERMISSIONS.get(role.name, set()))


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
                "permissions": sorted(get_role_permissions(role)),
                "tenant_bindings": tenant_role_map.get(role.name, []),
                "scopes": scopes_payload,
            }
        )
    return bindings


def build_access_context(db: Session, user: User) -> AccessContext:
    user_roles = sorted(user.roles, key=lambda item: item.name)
    role_names = {item.name for item in user_roles}
    permissions: set[str] = set()
    for role in user_roles:
        permissions.update(get_role_permissions(role))

    scope_set = ScopeSet()
    tenant_roles: list[UserTenantRoleView] = []
    data_scopes: list[UserDataScopeView] = []

    tenant_role_rows = list(
        db.execute(
            select(UserTenantRole)
            .where(UserTenantRole.user_id == user.id)
            .order_by(UserTenantRole.id.asc())
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
        db.execute(
            select(UserDataScope)
            .where(UserDataScope.user_id == user.id)
            .order_by(UserDataScope.id.asc())
        ).scalars()
    )
    if not scope_rows and ("admin" in role_names or "hq_noc" in role_names):
        scope_rows = [UserDataScope(user_id=user.id, scope_type="all", scope_value="*", scope_name="全部数据")]

    for row in scope_rows:
        scope_type = row.scope_type
        scope_value = row.scope_value
        scope_name = row.scope_name

        if scope_type == "all":
            scope_set.has_all = True
            scope_value = "*"
            scope_name = scope_name or "全部数据"
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
                scope_name = scope_name or project.name
        elif scope_type == "site":
            site = db.scalar(select(Site).where(Site.code == scope_value))
            if site is not None:
                scope_set.site_ids.add(site.id)
                scope_set.site_codes.add(site.code)
                scope_name = scope_name or site.name
        elif scope_type == "device_group":
            device_group = db.scalar(select(DeviceGroup).where(DeviceGroup.code == scope_value))
            if device_group is not None:
                scope_set.device_group_ids.add(device_group.id)
                scope_set.tenant_ids.add(device_group.tenant_id)
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
            select(DeviceGroup.site_id).where(
                DeviceGroup.project_id.in_(access.project_ids),
                DeviceGroup.site_id.is_not(None),
            )
        ).all()
        site_ids.update(project_site_ids)
    if access.tenant_ids:
        tenant_site_ids = db.scalars(
            select(TenantSiteBinding.site_id).where(TenantSiteBinding.tenant_id.in_(access.tenant_ids))
        ).all()
        site_ids.update(tenant_site_ids)
    if access.device_group_ids:
        device_group_site_ids = db.scalars(
            select(DeviceGroup.site_id).where(
                DeviceGroup.id.in_(access.device_group_ids),
                DeviceGroup.site_id.is_not(None),
            )
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
