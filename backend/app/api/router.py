from fastapi import APIRouter

from app.api.routes import (
    alarm_rules,
    alarms,
    auth,
    authz_roles,
    authz_users,
    custom_scope_sets,
    device_groups,
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
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(authz_roles.router)
api_router.include_router(authz_users.router)
api_router.include_router(projects.router)
api_router.include_router(device_groups.router)
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
