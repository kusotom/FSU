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
    CORE_ROLE_COMPANY,
    CORE_ROLE_EMPLOYEE,
    CORE_ROLE_PLATFORM,
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
        "rule_key": "mains_current_high",
        "rule_name": "\u5e02\u7535\u7535\u6d41\u8fc7\u9ad8",
        "category": "power",
        "metric_key": "mains_current",
        "alarm_code": "mains_current_high",
        "comparison": "gt",
        "threshold_value": 80.0,
        "duration_seconds": 30,
        "alarm_level": 2,
        "description": "\u5f53\u5e02\u7535\u7535\u6d41 > 80A \u65f6\u89e6\u53d1",
    },
    {
        "rule_key": "mains_frequency_high",
        "rule_name": "\u5e02\u7535\u9891\u7387\u8fc7\u9ad8",
        "category": "power",
        "metric_key": "mains_frequency",
        "alarm_code": "mains_frequency_high",
        "comparison": "gt",
        "threshold_value": 55.0,
        "duration_seconds": 30,
        "alarm_level": 3,
        "description": "\u5f53\u5e02\u7535\u9891\u7387 > 55Hz \u65f6\u89e6\u53d1",
    },
    {
        "rule_key": "mains_frequency_low",
        "rule_name": "\u5e02\u7535\u9891\u7387\u8fc7\u4f4e",
        "category": "power",
        "metric_key": "mains_frequency",
        "alarm_code": "mains_frequency_low",
        "comparison": "lt",
        "threshold_value": 45.0,
        "duration_seconds": 30,
        "alarm_level": 3,
        "description": "\u5f53\u5e02\u7535\u9891\u7387 < 45Hz \u65f6\u89e6\u53d1",
    },
    {
        "rule_key": "rectifier_output_voltage_high",
        "rule_name": "\u6574\u6d41\u8f93\u51fa\u7535\u538b\u8fc7\u9ad8",
        "category": "power",
        "metric_key": "rectifier_output_voltage",
        "alarm_code": "rectifier_output_voltage_high",
        "comparison": "gt",
        "threshold_value": 58.0,
        "duration_seconds": 30,
        "alarm_level": 2,
        "description": "\u5f53\u6574\u6d41\u8f93\u51fa\u7535\u538b > 58V \u65f6\u89e6\u53d1",
    },
    {
        "rule_key": "rectifier_output_voltage_low",
        "rule_name": "\u6574\u6d41\u8f93\u51fa\u7535\u538b\u8fc7\u4f4e",
        "category": "power",
        "metric_key": "rectifier_output_voltage",
        "alarm_code": "rectifier_output_voltage_low",
        "comparison": "lt",
        "threshold_value": 42.0,
        "duration_seconds": 30,
        "alarm_level": 2,
        "description": "\u5f53\u6574\u6d41\u8f93\u51fa\u7535\u538b < 42V \u65f6\u89e6\u53d1",
    },
    {
        "rule_key": "battery_group_voltage_high",
        "rule_name": "\u7535\u6c60\u7ec4\u7535\u538b\u8fc7\u9ad8",
        "category": "power",
        "metric_key": "battery_group_voltage",
        "alarm_code": "battery_group_voltage_high",
        "comparison": "gt",
        "threshold_value": 54.0,
        "duration_seconds": 60,
        "alarm_level": 2,
        "description": "\u5f53\u7535\u6c60\u7ec4\u7535\u538b > 54V \u65f6\u89e6\u53d1",
    },
    {
        "rule_key": "battery_group_voltage_low",
        "rule_name": "\u7535\u6c60\u7ec4\u7535\u538b\u8fc7\u4f4e",
        "category": "power",
        "metric_key": "battery_group_voltage",
        "alarm_code": "battery_group_voltage_low",
        "comparison": "lt",
        "threshold_value": 42.0,
        "duration_seconds": 60,
        "alarm_level": 1,
        "description": "\u5f53\u7535\u6c60\u7ec4\u7535\u538b < 42V \u65f6\u89e6\u53d1",
    },
    {
        "rule_key": "battery_temp_high",
        "rule_name": "\u7535\u6c60\u6e29\u5ea6\u8fc7\u9ad8",
        "category": "power",
        "metric_key": "battery_temp",
        "alarm_code": "battery_temp_high",
        "comparison": "gt",
        "threshold_value": 45.0,
        "duration_seconds": 60,
        "alarm_level": 2,
        "description": "\u5f53\u7535\u6c60\u6e29\u5ea6 > 45C \u65f6\u89e6\u53d1",
    },
    {
        "rule_key": "water_leak_alarm",
        "rule_name": "\u6c34\u6d78\u544a\u8b66",
        "category": "env",
        "metric_key": "water_leak_status",
        "alarm_code": "water_leak_alarm",
        "comparison": "eq",
        "threshold_value": 1.0,
        "duration_seconds": 10,
        "alarm_level": 1,
        "description": "\u5f53\u6c34\u6d78\u72b6\u6001 = 1 \u65f6\u89e6\u53d1",
    },
    {
        "rule_key": "smoke_alarm",
        "rule_name": "\u70df\u96fe\u544a\u8b66",
        "category": "env",
        "metric_key": "smoke_status",
        "alarm_code": "smoke_alarm",
        "comparison": "eq",
        "threshold_value": 1.0,
        "duration_seconds": 10,
        "alarm_level": 1,
        "description": "\u5f53\u70df\u96fe\u72b6\u6001 = 1 \u65f6\u89e6\u53d1",
    },
    {
        "rule_key": "ac_fault_alarm",
        "rule_name": "\u7a7a\u8c03\u6545\u969c",
        "category": "env",
        "metric_key": "ac_fault_status",
        "alarm_code": "ac_fault_alarm",
        "comparison": "eq",
        "threshold_value": 1.0,
        "duration_seconds": 30,
        "alarm_level": 2,
        "description": "\u5f53\u7a7a\u8c03\u6545\u969c\u72b6\u6001 = 1 \u65f6\u89e6\u53d1",
    },
    {
        "rule_key": "fresh_air_fault_alarm",
        "rule_name": "\u65b0\u98ce\u6545\u969c",
        "category": "env",
        "metric_key": "fresh_air_fault_status",
        "alarm_code": "fresh_air_fault_alarm",
        "comparison": "eq",
        "threshold_value": 1.0,
        "duration_seconds": 30,
        "alarm_level": 3,
        "description": "\u5f53\u65b0\u98ce\u6545\u969c\u72b6\u6001 = 1 \u65f6\u89e6\u53d1",
    },
    {
        "rule_key": "rectifier_fault_alarm",
        "rule_name": "\u6574\u6d41\u6545\u969c",
        "category": "power",
        "metric_key": "rectifier_fault_status",
        "alarm_code": "rectifier_fault_alarm",
        "comparison": "eq",
        "threshold_value": 1.0,
        "duration_seconds": 30,
        "alarm_level": 2,
        "description": "\u5f53\u6574\u6d41\u6545\u969c\u72b6\u6001 = 1 \u65f6\u89e6\u53d1",
    },
    {
        "rule_key": "battery_fault_alarm",
        "rule_name": "\u7535\u6c60\u6545\u969c",
        "category": "power",
        "metric_key": "battery_fault_status",
        "alarm_code": "battery_fault_alarm",
        "comparison": "eq",
        "threshold_value": 1.0,
        "duration_seconds": 30,
        "alarm_level": 2,
        "description": "\u5f53\u7535\u6c60\u6545\u969c\u72b6\u6001 = 1 \u65f6\u89e6\u53d1",
    },
    {
        "rule_key": "gen_fault_alarm",
        "rule_name": "\u6cb9\u673a\u6545\u969c",
        "category": "power",
        "metric_key": "gen_fault_status",
        "alarm_code": "gen_fault_alarm",
        "comparison": "eq",
        "threshold_value": 1.0,
        "duration_seconds": 30,
        "alarm_level": 2,
        "description": "\u5f53\u6cb9\u673a\u6545\u969c\u72b6\u6001 = 1 \u65f6\u89e6\u53d1",
    },
    {
        "rule_key": "dc_overcurrent_alarm",
        "rule_name": "\u76f4\u6d41\u8fc7\u6d41\u544a\u8b66",
        "category": "power",
        "metric_key": "dc_overcurrent",
        "alarm_code": "dc_overcurrent_alarm",
        "comparison": "eq",
        "threshold_value": 1.0,
        "duration_seconds": 15,
        "alarm_level": 2,
        "description": "\u5f53\u76f4\u6d41\u8fc7\u6d41\u72b6\u6001 = 1 \u65f6\u89e6\u53d1",
    },
    {
        "rule_key": "ups_bypass_alarm",
        "rule_name": "UPS\u65c1\u8def\u544a\u8b66",
        "category": "power",
        "metric_key": "ups_bypass_status",
        "alarm_code": "ups_bypass_alarm",
        "comparison": "eq",
        "threshold_value": 1.0,
        "duration_seconds": 30,
        "alarm_level": 3,
        "description": "\u5f53 UPS \u65c1\u8def\u72b6\u6001 = 1 \u65f6\u89e6\u53d1",
    },
    {
        "rule_key": "battery_fuse_alarm",
        "rule_name": "\u7535\u6c60\u7194\u4e1d\u544a\u8b66",
        "category": "power",
        "metric_key": "battery_fuse_status",
        "alarm_code": "battery_fuse_alarm",
        "comparison": "eq",
        "threshold_value": 1.0,
        "duration_seconds": 15,
        "alarm_level": 2,
        "description": "\u5f53\u7535\u6c60\u7194\u4e1d\u72b6\u6001 = 1 \u65f6\u89e6\u53d1",
    },
    {
        "rule_key": "gen_start_failed_alarm",
        "rule_name": "\u6cb9\u673a\u542f\u52a8\u5931\u8d25",
        "category": "power",
        "metric_key": "gen_start_failed",
        "alarm_code": "gen_start_failed_alarm",
        "comparison": "eq",
        "threshold_value": 1.0,
        "duration_seconds": 15,
        "alarm_level": 2,
        "description": "\u5f53\u6cb9\u673a\u542f\u52a8\u5931\u8d25\u72b6\u6001 = 1 \u65f6\u89e6\u53d1",
    },
    {
        "rule_key": "gen_fuel_low",
        "rule_name": "\u6cb9\u673a\u6cb9\u4f4d\u8fc7\u4f4e",
        "category": "power",
        "metric_key": "gen_fuel_level",
        "alarm_code": "gen_fuel_low",
        "comparison": "lt",
        "threshold_value": 20.0,
        "duration_seconds": 60,
        "alarm_level": 3,
        "description": "\u5f53\u6cb9\u673a\u6cb9\u4f4d < 20% \u65f6\u89e6\u53d1",
    },
    {
        "rule_key": "spd_failure_alarm",
        "rule_name": "\u9632\u96f7\u5668\u5931\u6548",
        "category": "power",
        "metric_key": "spd_failure",
        "alarm_code": "spd_failure_alarm",
        "comparison": "eq",
        "threshold_value": 1.0,
        "duration_seconds": 30,
        "alarm_level": 2,
        "description": "\u5f53\u9632\u96f7\u5668\u5931\u6548\u72b6\u6001 = 1 \u65f6\u89e6\u53d1",
    },
    {
        "rule_key": "ac_high_pressure_alarm",
        "rule_name": "\u7a7a\u8c03\u9ad8\u538b\u544a\u8b66",
        "category": "env",
        "metric_key": "ac_high_pressure",
        "alarm_code": "ac_high_pressure_alarm",
        "comparison": "eq",
        "threshold_value": 1.0,
        "duration_seconds": 30,
        "alarm_level": 2,
        "description": "\u5f53\u7a7a\u8c03\u9ad8\u538b\u72b6\u6001 = 1 \u65f6\u89e6\u53d1",
    },
    {
        "rule_key": "ac_low_pressure_alarm",
        "rule_name": "\u7a7a\u8c03\u4f4e\u538b\u544a\u8b66",
        "category": "env",
        "metric_key": "ac_low_pressure",
        "alarm_code": "ac_low_pressure_alarm",
        "comparison": "eq",
        "threshold_value": 1.0,
        "duration_seconds": 30,
        "alarm_level": 2,
        "description": "\u5f53\u7a7a\u8c03\u4f4e\u538b\u72b6\u6001 = 1 \u65f6\u89e6\u53d1",
    },
    {
        "rule_key": "ac_comm_alarm",
        "rule_name": "\u7a7a\u8c03\u901a\u4fe1\u5f02\u5e38",
        "category": "env",
        "metric_key": "ac_comm_status",
        "alarm_code": "ac_comm_alarm",
        "comparison": "ne",
        "threshold_value": 1.0,
        "duration_seconds": 30,
        "alarm_level": 3,
        "description": "\u5f53\u7a7a\u8c03\u901a\u4fe1\u72b6\u6001 \u2260 1 \u65f6\u89e6\u53d1",
    },
    {
        "rule_key": "camera_offline_alarm",
        "rule_name": "\u6444\u50cf\u5934\u79bb\u7ebf",
        "category": "smart",
        "metric_key": "camera_online_status",
        "alarm_code": "camera_offline_alarm",
        "comparison": "ne",
        "threshold_value": 1.0,
        "duration_seconds": 60,
        "alarm_level": 3,
        "description": "\u5f53\u6444\u50cf\u5934\u5728\u7ebf\u72b6\u6001 \u2260 1 \u65f6\u89e6\u53d1",
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


def _ensure_permission_role(db: Session, user: User) -> Role:
    role_name = f"user_perm_{user.id}"
    item = db.scalar(select(Role).where(Role.name == role_name))
    if item is None:
        item = Role(name=role_name, description=f"用户权限角色#{user.id}")
        db.add(item)
        db.flush()
        return item
    item.description = f"用户权限角色#{user.id}"
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
    phone: str | None = None,
    phone_country_code: str = "+86",
    status: str = "ACTIVE",
    is_active: bool = True,
) -> User:
    item = db.scalar(select(User).where(User.username == username))
    if item is None:
        item = User(
            username=username,
            password_hash=get_password_hash(password),
            phone_country_code=phone_country_code,
            phone=phone,
            full_name=full_name,
            status=status,
            is_active=is_active,
        )
        db.add(item)
        db.flush()
        return item
    if not item.password_hash:
        item.password_hash = get_password_hash(password)
    if phone is not None:
        item.phone_country_code = phone_country_code
        item.phone = phone
    item.full_name = full_name
    item.status = status
    item.is_active = is_active
    return item


def _bind_global_role(user: User, role: Role):
    exists = any(item.id == role.id for item in user.roles)
    if not exists:
        user.roles.append(role)


def _sync_user_roles(user: User, roles: list[Role]):
    user.roles = roles


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
    _hq, sub_a = seed_tenants(db)

    platform_role = _ensure_role(db, CORE_ROLE_PLATFORM, "平台管理员")
    company_role = _ensure_role(db, CORE_ROLE_COMPANY, "公司管理员")
    employee_role = _ensure_role(db, CORE_ROLE_EMPLOYEE, "普通员工")
    _sync_role_permissions(db, platform_role, BUILTIN_ROLE_DEFAULT_PERMISSIONS[CORE_ROLE_PLATFORM])
    _sync_role_permissions(db, company_role, BUILTIN_ROLE_DEFAULT_PERMISSIONS[CORE_ROLE_COMPANY])
    _sync_role_permissions(db, employee_role, BUILTIN_ROLE_DEFAULT_PERMISSIONS[CORE_ROLE_EMPLOYEE])

    admin = _ensure_user(
        db,
        username="admin",
        password="admin123",
        full_name="平台管理员",
    )
    _sync_user_roles(admin, [platform_role])
    admin.tenant_roles.clear()
    _set_user_data_scopes(db, admin, [("all", "*", "全部数据")])

    suba_admin = _ensure_user(
        db,
        username="suba_admin",
        password="admin123",
        full_name="A公司管理员",
    )
    suba_permission_role = _ensure_permission_role(db, suba_admin)
    _sync_role_permissions(db, suba_permission_role, {"site.view", "user.manage_company"})
    _sync_user_roles(suba_admin, [company_role, suba_permission_role])
    suba_admin.tenant_roles.clear()
    _bind_tenant_role(db, user=suba_admin, role=company_role, tenant=sub_a)
    _set_user_data_scopes(db, suba_admin, [("tenant", sub_a.code, sub_a.name)])

    employee_demo = _ensure_user(
        db,
        username="emp_demo",
        password="emp12345",
        full_name="示例员工",
    )
    employee_permission_role = _ensure_permission_role(db, employee_demo)
    _sync_role_permissions(
        db,
        employee_permission_role,
        {"dashboard.view", "realtime.view", "history.view", "alarm.view", "site.view"},
    )
    _sync_user_roles(employee_demo, [employee_role, employee_permission_role])
    employee_demo.tenant_roles.clear()
    _bind_tenant_role(db, user=employee_demo, role=employee_role, tenant=sub_a)
    _set_user_data_scopes(db, employee_demo, [("tenant", sub_a.code, sub_a.name)])

    for legacy_username in ("hq_noc", "suba_noc"):
        legacy_user = db.scalar(select(User).where(User.username == legacy_username))
        if legacy_user is not None:
            legacy_user.is_active = False


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

    admin_user = db.scalar(select(User).where(User.username == "suba_admin"))
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


def seed_roles_and_admin(db: Session):
    _hq, sub_a = seed_tenants(db)

    platform_role = _ensure_role(db, CORE_ROLE_PLATFORM, "平台管理员")
    company_role = _ensure_role(db, CORE_ROLE_COMPANY, "公司管理员")
    employee_role = _ensure_role(db, CORE_ROLE_EMPLOYEE, "普通员工")
    _sync_role_permissions(db, platform_role, BUILTIN_ROLE_DEFAULT_PERMISSIONS[CORE_ROLE_PLATFORM])
    _sync_role_permissions(db, company_role, BUILTIN_ROLE_DEFAULT_PERMISSIONS[CORE_ROLE_COMPANY])
    _sync_role_permissions(db, employee_role, BUILTIN_ROLE_DEFAULT_PERMISSIONS[CORE_ROLE_EMPLOYEE])

    admin = _ensure_user(
        db,
        username="admin",
        password="admin123",
        full_name="平台管理员",
        phone="13800000001",
        status="ACTIVE",
    )
    _sync_user_roles(admin, [platform_role])
    admin.tenant_roles.clear()
    _set_user_data_scopes(db, admin, [("all", "*", "全部数据")])

    suba_admin = _ensure_user(
        db,
        username="suba_admin",
        password="admin123",
        full_name="A公司管理员",
        phone="13800000002",
        status="ACTIVE",
    )
    suba_permission_role = _ensure_permission_role(db, suba_admin)
    _sync_role_permissions(db, suba_permission_role, {"site.view", "user.manage_company"})
    _sync_user_roles(suba_admin, [company_role, suba_permission_role])
    suba_admin.tenant_roles.clear()
    _bind_tenant_role(db, user=suba_admin, role=company_role, tenant=sub_a)
    _set_user_data_scopes(db, suba_admin, [("tenant", sub_a.code, sub_a.name)])

    employee_demo = _ensure_user(
        db,
        username="emp_demo",
        password="emp12345",
        full_name="示例员工",
        phone="13800000003",
        status="ACTIVE",
    )
    employee_permission_role = _ensure_permission_role(db, employee_demo)
    _sync_role_permissions(
        db,
        employee_permission_role,
        {"dashboard.view", "realtime.view", "history.view", "alarm.view", "site.view"},
    )
    _sync_user_roles(employee_demo, [employee_role, employee_permission_role])
    employee_demo.tenant_roles.clear()
    _bind_tenant_role(db, user=employee_demo, role=employee_role, tenant=sub_a)
    _set_user_data_scopes(db, employee_demo, [("tenant", sub_a.code, sub_a.name)])

    for legacy_username in ("hq_noc", "suba_noc"):
        legacy_user = db.scalar(select(User).where(User.username == legacy_username))
        if legacy_user is not None:
            legacy_user.is_active = False
