from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.deps_authz import permission_required
from app.db.session import get_db
from app.models.alarm import AlarmActionLog, AlarmEvent
from app.models.user import User
from app.schemas.alarm import AlarmResponse
from app.services.access_control import AccessContext, get_accessible_site_ids

router = APIRouter(prefix="/alarms", tags=["alarms"])


@router.get("", response_model=list[AlarmResponse])
def list_alarms(
    response: Response,
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=20, le=500),
    db: Session = Depends(get_db),
    access: AccessContext = Depends(permission_required("alarm.view")),
):
    stmt = select(AlarmEvent)
    count_stmt = select(func.count(AlarmEvent.id))
    scoped_ids = get_accessible_site_ids(db, access)
    if scoped_ids is not None:
        if not scoped_ids:
            response.headers["X-Total-Count"] = "0"
            response.headers["X-Page"] = str(page)
            response.headers["X-Page-Size"] = str(page_size)
            return []
        stmt = stmt.where(AlarmEvent.site_id.in_(scoped_ids))
        count_stmt = count_stmt.where(AlarmEvent.site_id.in_(scoped_ids))
    if status:
        stmt = stmt.where(AlarmEvent.status == status)
        count_stmt = count_stmt.where(AlarmEvent.status == status)

    total = int(db.scalar(count_stmt) or 0)
    offset = (page - 1) * page_size
    rows = list(db.scalars(stmt.order_by(AlarmEvent.started_at.desc()).offset(offset).limit(page_size)).all())
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Page"] = str(page)
    response.headers["X-Page-Size"] = str(page_size)
    return rows


@router.post("/{alarm_id}/ack", response_model=AlarmResponse)
def ack_alarm(
    alarm_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    access: AccessContext = Depends(permission_required("alarm.ack")),
):
    alarm = db.get(AlarmEvent, alarm_id)
    if alarm is None:
        raise HTTPException(status_code=404, detail="告警不存在")
    scoped_ids = get_accessible_site_ids(db, access)
    if scoped_ids is not None and alarm.site_id not in scoped_ids:
        raise HTTPException(status_code=403, detail="无权处理该告警")
    if alarm.status != "active":
        raise HTTPException(status_code=409, detail="仅活动状态告警可确认")

    alarm.status = "acknowledged"
    alarm.acknowledged_at = datetime.now(timezone.utc)
    alarm.acknowledged_by = user.id
    alarm.updated_at = datetime.now(timezone.utc)
    db.add(
        AlarmActionLog(
            alarm_id=alarm.id,
            action="ack",
            operator_id=user.id,
            content=f"告警已确认: {alarm.content}",
        )
    )
    db.commit()
    db.refresh(alarm)
    return alarm


@router.post("/{alarm_id}/close", response_model=AlarmResponse)
def close_alarm(
    alarm_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    access: AccessContext = Depends(permission_required("alarm.close")),
):
    alarm = db.get(AlarmEvent, alarm_id)
    if alarm is None:
        raise HTTPException(status_code=404, detail="告警不存在")
    scoped_ids = get_accessible_site_ids(db, access)
    if scoped_ids is not None and alarm.site_id not in scoped_ids:
        raise HTTPException(status_code=403, detail="无权处理该告警")
    if alarm.status == "closed":
        raise HTTPException(status_code=409, detail="告警已关闭，无需重复操作")

    alarm.status = "closed"
    alarm.closed_at = datetime.now(timezone.utc)
    alarm.closed_by = user.id
    alarm.updated_at = datetime.now(timezone.utc)
    db.add(
        AlarmActionLog(
            alarm_id=alarm.id,
            action="close",
            operator_id=user.id,
            content=f"告警已关闭: {alarm.content}",
        )
    )
    db.commit()
    db.refresh(alarm)
    return alarm
