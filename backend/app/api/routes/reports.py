from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_access_context, get_current_user
from app.db.session import get_db
from app.models.alarm import AlarmEvent
from app.models.site import Site
from app.services.access_control import AccessContext, get_accessible_site_ids

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/alarm-summary")
def alarm_summary(
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
    access: AccessContext = Depends(get_access_context),
):
    scoped_ids = get_accessible_site_ids(db, access)
    alarm_total_stmt = select(func.count(AlarmEvent.id))
    alarm_active_stmt = select(func.count(AlarmEvent.id)).where(
        AlarmEvent.status.in_(["active", "acknowledged"])
    )
    alarm_recovered_stmt = select(func.count(AlarmEvent.id)).where(AlarmEvent.status == "recovered")
    alarm_closed_stmt = select(func.count(AlarmEvent.id)).where(AlarmEvent.status == "closed")
    site_count_stmt = select(func.count(Site.id))
    if scoped_ids is not None:
        if not scoped_ids:
            return {
                "site_count": 0,
                "alarm_total": 0,
                "alarm_active": 0,
                "alarm_recovered": 0,
                "alarm_closed": 0,
            }
        alarm_total_stmt = alarm_total_stmt.where(AlarmEvent.site_id.in_(scoped_ids))
        alarm_active_stmt = alarm_active_stmt.where(AlarmEvent.site_id.in_(scoped_ids))
        alarm_recovered_stmt = alarm_recovered_stmt.where(AlarmEvent.site_id.in_(scoped_ids))
        alarm_closed_stmt = alarm_closed_stmt.where(AlarmEvent.site_id.in_(scoped_ids))
        site_count_stmt = site_count_stmt.where(Site.id.in_(scoped_ids))

    total = db.scalar(alarm_total_stmt) or 0
    active = db.scalar(alarm_active_stmt) or 0
    recovered = db.scalar(alarm_recovered_stmt) or 0
    closed = db.scalar(alarm_closed_stmt) or 0
    site_count = db.scalar(site_count_stmt) or 0

    return {
        "site_count": site_count,
        "alarm_total": total,
        "alarm_active": active,
        "alarm_recovered": recovered,
        "alarm_closed": closed,
    }
