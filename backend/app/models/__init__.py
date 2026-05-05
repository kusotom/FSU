from app.models.auth_sms import AuthSmsCode, AuthSmsDeliveryLog, SmsCodeLog
from app.models.notify import NotifyChannel, NotifyPolicy
from app.models.notify_admin import (
    AlarmPushLog,
    NotifyGroup,
    NotifyGroupMember,
    NotifyReceiver,
    NotifyRule,
    OncallSchedule,
    OncallScheduleMember,
)
from app.models.alarm import AlarmActionLog, AlarmConditionState, AlarmEvent
from app.models.custom_scope import CustomScopeItem, CustomScopeSet
from app.models.device import FSUDevice, MonitorPoint
from app.models.device_group import DeviceGroup
from app.models.operation_log import OperationLog
from app.models.project import Project
from app.models.rule import AlarmRule, AlarmRuleTenantPolicy
from app.models.site import Site
from app.models.tenant import Tenant, TenantSiteBinding, UserTenantRole
from app.models.telemetry import TelemetryHistory, TelemetryLatest
from app.models.system_config import SystemConfig
from app.models.user import Role, RolePermission, User, UserDataScope, user_roles
from app.models.b_device import BDevice, BDeviceConfig
from app.models.b_interface_alarm import BInterfaceAlarmHistory, BInterfaceCurrentAlarm
from app.models.b_interface_fsu_status import BInterfaceFsuStatus
from app.models.b_interface_history import BInterfaceHistory
from app.models.b_interface_info_cache import BInterfaceFsuInfoCache, BInterfaceLoginInfoCache
from app.models.b_interface_outbound_call import BInterfaceOutboundCall
from app.models.b_interface_realtime import BInterfaceRealtime

__all__ = [
    "User",
    "Role",
    "RolePermission",
    "user_roles",
    "UserDataScope",
    "Site",
    "Tenant",
    "TenantSiteBinding",
    "UserTenantRole",
    "FSUDevice",
    "MonitorPoint",
    "TelemetryLatest",
    "TelemetryHistory",
    "SystemConfig",
    "AlarmEvent",
    "AlarmActionLog",
    "AlarmConditionState",
    "AlarmRule",
    "AlarmRuleTenantPolicy",
    "NotifyChannel",
    "NotifyPolicy",
    "NotifyReceiver",
    "NotifyGroup",
    "NotifyGroupMember",
    "NotifyRule",
    "OncallSchedule",
    "OncallScheduleMember",
    "AlarmPushLog",
    "OperationLog",
    "Project",
    "DeviceGroup",
    "CustomScopeSet",
    "CustomScopeItem",
    "SmsCodeLog",
    "AuthSmsCode",
    "AuthSmsDeliveryLog",
    "BDevice",
    "BDeviceConfig",
    "BInterfaceCurrentAlarm",
    "BInterfaceAlarmHistory",
    "BInterfaceFsuStatus",
    "BInterfaceHistory",
    "BInterfaceFsuInfoCache",
    "BInterfaceLoginInfoCache",
    "BInterfaceOutboundCall",
    "BInterfaceRealtime",
]
