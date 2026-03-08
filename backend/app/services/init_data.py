from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import get_password_hash
from app.models.custom_scope import CustomScopeItem, CustomScopeSet
from app.models.device import FSUDevice, MonitorPoint
from app.models.device_group import DeviceGroup
from app.models.project import Project
from app.models.rule import AlarmRule
from app.models.site import Site
from app.models.tenant import Tenant, TenantSiteBinding, UserTenantRole
from app.models.user import Role, RolePermission, User, UserDataScope
from app.services.access_control import (
    BUILTIN_ROLE_DEFAULT_PERMISSIONS,
    DEFAULT_SUB_TENANT_CODE,
    HQ_TENANT_CODE,
    ensure_site_tenant_binding,
    expand_permissions,
)

DEFAULT_POINTS = [
    ("mains_voltage", "\u5e02\u7535\u7535\u538b", "power", "V", 260.0, 170.0),
    ("room_temp", "\u673a\u623f\u6e29\u5ea6", "env", "C", 35.0, 5.0),
    ("room_humidity", "\u673a\u623f\u6e7f\u5ea6", "env", "%", 90.0, 10.0),
]

DEFAULT_ALARM_RULES: list[dict] = [
    {
        "rule_key": "mains_voltage_high",
        "rule_name": "\u5e02\u7535\u7535\u538b\u8fc7\u9ad8",
        "category": "power",
        "metric_key": "mains_voltage",
        "alarm_code": "mains_voltage_high",
        "comparison": "gt",
        "threshold_value": 260.0,
        "duration_seconds": 30,
        "alarm_level": 2,
        "description": "\u5f53\u5e02\u7535\u7535\u538b > 260V \u65f6\u89e6\u53d1",
    },
    {
        "rule_key": "mains_voltage_low",
        "rule_name": "\u5e02\u7535\u7535\u538b\u8fc7\u4f4e",
        "category": "power",
        "metric_key": "mains_voltage",
        "alarm_code": "mains_voltage_low",
        "comparison": "lt",
        "threshold_value": 170.0,
        "duration_seconds": 30,
        "alarm_level": 2,
        "description": "\u5f53\u5e02\u7535\u7535\u538b < 170V \u65f6\u89e6\u53d1",
    },
    {
        "rule_key": "room_temp_high",
        "rule_name": "\u673a\u623f\u6e29\u5ea6\u8fc7\u9ad8",
        "category": "env",
        "metric_key": "room_temp",
        "alarm_code": "room_temp_high",
        "comparison": "gt",
        "threshold_value": 35.0,
        "duration_seconds": 60,
        "alarm_level": 2,
        "description": "\u5f53\u673a\u623f\u6e29\u5ea6 > 35C \u65f6\u89e6\u53d1",
    },
    {
        "rule_key": "room_temp_low",
        "rule_name": "\u673a\u623f\u6e29\u5ea6\u8fc7\u4f4e",
        "category": "env",
        "metric_key": "room_temp",
        "alarm_code": "room_temp_low",
        "comparison": "lt",
        "threshold_value": 5.0,
        "duration_seconds": 60,
        "alarm_level": 2,
        "description": "\u5f53\u673a\u623f\u6e29\u5ea6 < 5C \u65f6\u89e6\u53d1",
    },
    {
        "rule_key": "room_humidity_high",
        "rule_name": "\u673a\u623f\u6e7f\u5ea6\u8fc7\u9ad8",
        "category": "env",
        "metric_key": "room_humidity",
        "alarm_code": "room_humidity_high",
        "comparison": "gt",
        "threshold_value": 90.0,
        "duration_seconds": 60,
        "alarm_level": 3,
        "description": "\u5f53\u673a\u623f\u6e7f\u5ea6 > 90% \u65f6\u89e6\u53d1",
    },
    {
        "rule_key": "room_humidity_low",
        "rule_name": "\u673a\u623f\u6e7f\u5ea6\u8fc7\u4f4e",
        "category": "env",
        "metric_key": "room_humidity",
        "alarm_code": "room_humidity_low",
        "comparison": "lt",
        "threshold_value": 10.0,
        "duration_seconds": 60,
        "alarm_level": 3,
        "description": "\u5f53\u673a\u623f\u6e7f\u5ea6 < 10% \u65f6\u89e6\u53d1",
    },
    {
        "rule_key": "fsu_heartbeat_timeout",
        "rule_name": "\u8bbe\u5907\u5fc3\u8df3\u8d85\u65f6",
        "category": "system",
        "metric_key": None,
        "alarm_code": "fsu_offline",
        "comparison": "stale_minutes",
        "threshold_value": 5.0,
        "duration_seconds": 30,
        "alarm_level": 1,
        "description": "\u5f53\u8bbe\u5907\u5fc3\u8df3\u8d85\u8fc7 5 \u5206\u949f\u672a\u66f4\u65b0\u65f6\u89e6\u53d1",
    },
]


def seed_tenants(db: Session) -> tuple[Tenant, Tenant]:
    hq = db.scalar(select(Tenant).where(Tenant.code == HQ_TENANT_CODE))
    if hq is None:
        hq = Tenant(
            code=HQ_TENANT_CODE,
            name="\u96c6\u56e2/\u603b\u90e8\u76d1\u63a7\u7ec4",
            tenant_type="group",
            is_active=True,
        )
        db.add(hq)
        db.flush()
    else:
        hq.name = "\u96c6\u56e2/\u603b\u90e8\u76d1\u63a7\u7ec4"
        hq.tenant_type = "group"
        hq.is_active = True

    sub_a = db.scalar(select(Tenant).where(Tenant.code == DEFAULT_SUB_TENANT_CODE))
    if sub_a is None:
        sub_a = Tenant(
            code=DEFAULT_SUB_TENANT_CODE,
            name="\u5b50\u516c\u53f8A\u76d1\u63a7\u7ec4",
            tenant_type="subsidiary",
            parent_id=hq.id,
            is_active=True,
        )
        db.add(sub_a)
        db.flush()
    else:
        sub_a.name = "\u5b50\u516c\u53f8A\u76d1\u63a7\u7ec4"
        sub_a.tenant_type = "subsidiary"
        sub_a.parent_id = hq.id
        sub_a.is_active = True

    return hq, sub_a


def _ensure_role(db: Session, name: str, description: str) -> Role:
    item = db.scalar(select(Role).where(Role.name == name))
    if item is None:
        item = Role(name=name, description=description)
        db.add(item)
        db.flush()
        return item
    item.description = description
    return item


def _sync_role_permissions(db: Session, role: Role, permission_keys: set[str]):
    permission_keys = expand_permissions(permission_keys)
    existing = {item.permission_key: item for item in role.permissions}
    for key in list(existing.keys()):
        if key not in permission_keys:
            db.delete(existing[key])
    for key in sorted(permission_keys):
        if key in existing:
            continue
        db.add(RolePermission(role_id=role.id, permission_key=key))


def _set_user_data_scopes(db: Session, user: User, scopes: list[tuple[str, str, str | None]]):
    existing = {(item.scope_type, item.scope_value): item for item in user.data_scopes}
    expected = {(scope_type, scope_value) for scope_type, scope_value, _ in scopes}
    for key, item in existing.items():
        if key not in expected:
            db.delete(item)
    for scope_type, scope_value, scope_name in scopes:
        item = existing.get((scope_type, scope_value))
        if item is None:
            db.add(
                UserDataScope(
                    user_id=user.id,
                    scope_type=scope_type,
                    scope_value=scope_value,
                    scope_name=scope_name,
                )
            )
            continue
        item.scope_name = scope_name


def _ensure_user(
    db: Session,
    *,
    username: str,
    password: str,
    full_name: str,
    is_active: bool = True,
) -> User:
    item = db.scalar(select(User).where(User.username == username))
    if item is None:
        item = User(
            username=username,
            password_hash=get_password_hash(password),
            full_name=full_name,
            is_active=is_active,
        )
        db.add(item)
        db.flush()
        return item
    if not item.password_hash:
        item.password_hash = get_password_hash(password)
    item.full_name = full_name
    item.is_active = is_active
    return item


def _bind_global_role(user: User, role: Role):
    exists = any(item.id == role.id for item in user.roles)
    if not exists:
        user.roles.append(role)


def _bind_tenant_role(db: Session, *, user: User, role: Role, tenant: Tenant):
    exists = db.scalar(
        select(UserTenantRole).where(
            UserTenantRole.user_id == user.id,
            UserTenantRole.role_id == role.id,
            UserTenantRole.tenant_id == tenant.id,
        )
    )
    if exists:
        return
    db.add(
        UserTenantRole(
            user_id=user.id,
            role_id=role.id,
            tenant_id=tenant.id,
            scope_level="tenant",
        )
    )


def seed_roles_and_admin(db: Session):
    hq, sub_a = seed_tenants(db)

    admin_role = _ensure_role(db, "admin", "\u7cfb\u7edf\u7ba1\u7406\u5458")
    operator_role = _ensure_role(db, "operator", "\u8fd0\u7ef4\u4eba\u5458")
    hq_noc_role = _ensure_role(db, "hq_noc", "\u603b\u90e8\u76d1\u63a7\u7ec4")
    sub_noc_role = _ensure_role(db, "sub_noc", "\u5b50\u516c\u53f8\u76d1\u63a7\u7ec4")
    _sync_role_permissions(db, admin_role, BUILTIN_ROLE_DEFAULT_PERMISSIONS["admin"])
    _sync_role_permissions(db, operator_role, BUILTIN_ROLE_DEFAULT_PERMISSIONS["operator"])
    _sync_role_permissions(db, hq_noc_role, BUILTIN_ROLE_DEFAULT_PERMISSIONS["hq_noc"])
    _sync_role_permissions(db, sub_noc_role, BUILTIN_ROLE_DEFAULT_PERMISSIONS["sub_noc"])

    admin = _ensure_user(
        db,
        username="admin",
        password="admin123",
        full_name="\u7cfb\u7edf\u7ba1\u7406\u5458",
    )
    _bind_global_role(admin, admin_role)
    _bind_global_role(admin, operator_role)
    _bind_global_role(admin, hq_noc_role)
    _bind_tenant_role(db, user=admin, role=admin_role, tenant=hq)
    _bind_tenant_role(db, user=admin, role=hq_noc_role, tenant=hq)
    _set_user_data_scopes(db, admin, [("all", "*", "全部数据")])

    hq_noc = _ensure_user(
        db,
        username="hq_noc",
        password="noc12345",
        full_name="\u603b\u90e8NOC",
    )
    _bind_global_role(hq_noc, operator_role)
    _bind_global_role(hq_noc, hq_noc_role)
    _bind_tenant_role(db, user=hq_noc, role=hq_noc_role, tenant=hq)
    _set_user_data_scopes(db, hq_noc, [("all", "*", "全部数据")])

    suba_noc = _ensure_user(
        db,
        username="suba_noc",
        password="noc12345",
        full_name="\u5b50\u516c\u53f8A NOC",
    )
    _bind_global_role(suba_noc, operator_role)
    _bind_global_role(suba_noc, sub_noc_role)
    _bind_tenant_role(db, user=suba_noc, role=sub_noc_role, tenant=sub_a)
    _set_user_data_scopes(db, suba_noc, [("tenant", sub_a.code, sub_a.name)])


def seed_alarm_rules(db: Session):
    for payload in DEFAULT_ALARM_RULES:
        exists = db.scalar(select(AlarmRule).where(AlarmRule.rule_key == payload["rule_key"]))
        now = datetime.now(timezone.utc)
        if exists is None:
            db.add(
                AlarmRule(
                    **payload,
                    is_enabled=True,
                    created_at=now,
                    updated_at=now,
                )
            )
            continue

        exists.rule_name = payload["rule_name"]
        exists.category = payload["category"]
        exists.metric_key = payload["metric_key"]
        exists.alarm_code = payload["alarm_code"]
        exists.comparison = payload["comparison"]
        exists.threshold_value = payload["threshold_value"]
        exists.duration_seconds = payload["duration_seconds"]
        exists.alarm_level = payload["alarm_level"]
        exists.description = payload["description"]
        exists.updated_at = now


def seed_demo_site_data(db: Session):
    _, sub_a = seed_tenants(db)

    site = db.scalar(select(Site).where(Site.code == "SITE-001"))
    if site is None:
        site = Site(code="SITE-001", name="\u793a\u4f8b\u7ad9\u70b9", region="\u9ed8\u8ba4\u533a\u57df")
        db.add(site)
        db.flush()
    else:
        site.name = "\u793a\u4f8b\u7ad9\u70b9"
        site.region = "\u9ed8\u8ba4\u533a\u57df"

    ensure_site_tenant_binding(db, site_id=site.id, tenant_id=sub_a.id)
    # Ensure the binding is visible before querying "unbound" sites below.
    db.flush()

    project = db.scalar(
        select(Project).where(
            Project.tenant_id == sub_a.id,
            Project.code == "PROJ-001",
        )
    )
    if project is None:
        project = Project(
            tenant_id=sub_a.id,
            code="PROJ-001",
            name="A公司示例项目",
            status="active",
        )
        db.add(project)
        db.flush()
    else:
        project.name = "A公司示例项目"
        project.status = "active"

    device_group = db.scalar(
        select(DeviceGroup).where(
            DeviceGroup.tenant_id == sub_a.id,
            DeviceGroup.code == "DG-001",
        )
    )
    if device_group is None:
        device_group = DeviceGroup(
            tenant_id=sub_a.id,
            project_id=project.id,
            site_id=site.id,
            code="DG-001",
            name="核心设备组",
        )
        db.add(device_group)
        db.flush()
    else:
        device_group.project_id = project.id
        device_group.site_id = site.id
        device_group.name = "核心设备组"

    device = db.scalar(select(FSUDevice).where(FSUDevice.code == "FSU-001"))
    if device is None:
        device = FSUDevice(
            site_id=site.id,
            code="FSU-001",
            name="\u793a\u4f8bFSU\u4e3b\u673a",
            status="online",
            last_seen_at=datetime.now(timezone.utc),
        )
        db.add(device)
        db.flush()
    else:
        device.site_id = site.id
        device.name = "\u793a\u4f8bFSU\u4e3b\u673a"

    for point_key, point_name, category, unit, high, low in DEFAULT_POINTS:
        exists = db.scalar(
            select(MonitorPoint).where(
                MonitorPoint.device_id == device.id, MonitorPoint.point_key == point_key
            )
        )
        if exists is None:
            db.add(
                MonitorPoint(
                    device_id=device.id,
                    point_key=point_key,
                    point_name=point_name,
                    category=category,
                    unit=unit,
                    high_threshold=high,
                    low_threshold=low,
                )
            )
            continue

        exists.point_name = point_name
        exists.category = category
        exists.unit = unit
        exists.high_threshold = high
        exists.low_threshold = low

    admin_user = db.scalar(select(User).where(User.username == "suba_noc"))
    default_scope = db.scalar(
        select(CustomScopeSet).where(
            CustomScopeSet.tenant_id == sub_a.id,
            CustomScopeSet.name == "默认重点站点",
        )
    )
    if default_scope is None:
        default_scope = CustomScopeSet(
            tenant_id=sub_a.id,
            name="默认重点站点",
            resource_type="site",
            created_by=admin_user.id if admin_user else None,
        )
        db.add(default_scope)
        db.flush()
    else:
        default_scope.resource_type = "site"

    has_site_item = db.scalar(
        select(CustomScopeItem).where(
            CustomScopeItem.scope_set_id == default_scope.id,
            CustomScopeItem.resource_id == site.id,
        )
    )
    if has_site_item is None:
        db.add(CustomScopeItem(scope_set_id=default_scope.id, resource_id=site.id))

    unbound_site_ids = list(
        db.scalars(
            select(Site.id)
            .outerjoin(TenantSiteBinding, TenantSiteBinding.site_id == Site.id)
            .where(TenantSiteBinding.id.is_(None), Site.id != site.id)
        ).all()
    )
    for site_id in unbound_site_ids:
        ensure_site_tenant_binding(db, site_id=site_id, tenant_id=sub_a.id)
