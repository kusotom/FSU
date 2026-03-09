from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.deps_authz import permission_required
from app.db.session import get_db
from app.models.notify_admin import AlarmPushLog
from app.models.user import User
from app.schemas.notify_admin import AlarmPushLogResponse
from app.services.notify_guard import ensure_scope_allowed, ensure_tenant_allowed, get_tenant_by_code_or_404
from app.services.notifier import retry_alarm_push_log
from app.services.operation_log import write_operation_log

router = APIRouter(prefix="/notify-push-logs", tags=["notify-push-logs"])


def _mask_target(channel_type: str, target: str) -> str:
    raw = str(target or "")
    if channel_type == "pushplus":
        return raw[:6] + "..." + raw[-4:] if len(raw) > 12 else raw
    if channel_type == "sms_tencent":
        items = []
        for part in raw.split(","):
            part = part.strip()
            if len(part) > 7:
                items.append(part[:3] + "****" + part[-4:])
            else:
                items.append(part)
        return ",".join(items)
    if raw.startswith("http"):
        return raw[:32] + "..." if len(raw) > 35 else raw
    return raw


def _to_response(item: AlarmPushLog, tenant_code: str) -> AlarmPushLogResponse:
    return AlarmPushLogResponse(
        id=item.id,
        tenant_code=tenant_code,
        alarm_id=item.alarm_id,
        policy_name=item.policy_name,
        channel_name=item.channel_name,
        channel_type=item.channel_type,
        target=_mask_target(item.channel_type, item.target),
        title=item.title,
        content=item.content,
        push_status=item.push_status,
        error_message=item.error_message,
        retry_count=item.retry_count,
        pushed_at=item.pushed_at,
    )


@router.get("", response_model=list[AlarmPushLogResponse])
def list_push_logs(
    tenant_code: str,
    limit: int = 100,
    db: Session = Depends(get_db),
    access=Depends(permission_required("notify.push_log.view")),
):
    tenant = get_tenant_by_code_or_404(db, tenant_code)
    ensure_tenant_allowed(access, tenant.id)
    rows = list(
        db.scalars(
            select(AlarmPushLog)
            .where(AlarmPushLog.tenant_id == tenant.id)
            .order_by(AlarmPushLog.id.desc())
            .limit(max(1, min(limit, 500)))
        ).all()
    )
    filtered = []
    for item in rows:
        try:
            ensure_scope_allowed(
                db,
                access,
                tenant_id=item.tenant_id,
                project_id=item.project_id,
                site_id=item.site_id,
                device_group_id=item.device_group_id,
            )
        except HTTPException:
            continue
        filtered.append(_to_response(item, tenant.code))
    return filtered


@router.post("/{log_id}/retry")
async def retry_push_log(
    log_id: int,
    tenant_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    access=Depends(permission_required("notify.push_log.retry")),
):
    tenant = get_tenant_by_code_or_404(db, tenant_code)
    item = db.get(AlarmPushLog, log_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="推送日志不存在")
    ensure_tenant_allowed(access, tenant.id)
    if item.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="禁止跨租户重发推送日志")
    ensure_scope_allowed(
        db,
        access,
        tenant_id=item.tenant_id,
        project_id=item.project_id,
        site_id=item.site_id,
        device_group_id=item.device_group_id,
    )

    ok, detail = await retry_alarm_push_log(item)
    item.retry_count += 1
    item.push_status = "SUCCESS" if ok else "FAILED"
    item.error_message = None if ok else detail
    item.pushed_at = datetime.now(timezone.utc)
    write_operation_log(
        db,
        operator_id=current_user.id,
        tenant_id=tenant.id,
        action="notify_push_log.retry",
        target_type="alarm_push_log",
        target_id=str(item.id),
        content=f"重发推送日志#{item.id}，结果={'成功' if ok else '失败'}",
    )
    db.commit()
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
    return {"ok": True, "detail": detail}
