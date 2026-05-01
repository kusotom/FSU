from fastapi import APIRouter

from app.api.routes import (
    alarm_rules,
    alarms,
    auth,
    auth_sms,
    b_interface_2016,
    authz_roles,
    authz_users,
    custom_scope_sets,
    device_groups,
    fsu_debug,
    ingest,
    notify,
    notify_groups,
    notify_oncall,
    notify_push_logs,
    notify_receivers,
    notify_rules,
    operation_logs,
    projects,
    reports,
    sites,
    telemetry,
    tenants,
    users,
    webhooks_unisms,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(auth_sms.router)
api_router.include_router(b_interface_2016.router)
api_router.include_router(authz_roles.router)
api_router.include_router(authz_users.router)
api_router.include_router(projects.router)
api_router.include_router(device_groups.router)
api_router.include_router(fsu_debug.router)
api_router.include_router(custom_scope_sets.router)
api_router.include_router(operation_logs.router)
api_router.include_router(notify_receivers.router)
api_router.include_router(notify_groups.router)
api_router.include_router(notify_rules.router)
api_router.include_router(notify_oncall.router)
api_router.include_router(notify_push_logs.router)
api_router.include_router(tenants.router)
api_router.include_router(sites.router)
api_router.include_router(ingest.router)
api_router.include_router(telemetry.router)
api_router.include_router(alarms.router)
api_router.include_router(alarm_rules.router)
api_router.include_router(users.router)
api_router.include_router(reports.router)
api_router.include_router(notify.router)
api_router.include_router(webhooks_unisms.router)
