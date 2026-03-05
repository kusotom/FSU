from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_template_manager
from app.db.session import get_db
from app.models.notify import NotifyChannel, NotifyPolicy
from app.schemas.notify import (
    NotifyChannelCreate,
    NotifyChannelResponse,
    NotifyPolicyCreate,
    NotifyPolicyResponse,
)

router = APIRouter(prefix="/notify", tags=["notify"])


@router.get("/channels", response_model=list[NotifyChannelResponse])
def list_channels(db: Session = Depends(get_db), _=Depends(require_template_manager)):
    return list(db.scalars(select(NotifyChannel).order_by(NotifyChannel.id.desc())).all())


@router.post("/channels", response_model=NotifyChannelResponse)
def create_channel(
    payload: NotifyChannelCreate,
    db: Session = Depends(get_db),
    _=Depends(require_template_manager),
):
    exists = db.scalar(select(NotifyChannel).where(NotifyChannel.name == payload.name))
    if exists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="\u901a\u77e5\u901a\u9053\u540d\u79f0\u5df2\u5b58\u5728",
        )
    item = NotifyChannel(
        name=payload.name,
        channel_type=payload.channel_type,
        endpoint=payload.endpoint,
        secret=payload.secret,
        is_enabled=payload.is_enabled,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/policies", response_model=list[NotifyPolicyResponse])
def list_policies(db: Session = Depends(get_db), _=Depends(require_template_manager)):
    return list(db.scalars(select(NotifyPolicy).order_by(NotifyPolicy.id.desc())).all())


@router.post("/policies", response_model=NotifyPolicyResponse)
def create_policy(
    payload: NotifyPolicyCreate,
    db: Session = Depends(get_db),
    _=Depends(require_template_manager),
):
    exists = db.scalar(select(NotifyPolicy).where(NotifyPolicy.name == payload.name))
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="\u7b56\u7565\u540d\u79f0\u5df2\u5b58\u5728")
    channel = db.get(NotifyChannel, payload.channel_id)
    if channel is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="\u901a\u77e5\u901a\u9053\u4e0d\u5b58\u5728")

    item = NotifyPolicy(
        name=payload.name,
        channel_id=payload.channel_id,
        min_alarm_level=payload.min_alarm_level,
        event_types=payload.event_types,
        is_enabled=payload.is_enabled,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item
