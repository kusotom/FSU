from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_template_manager
from app.db.session import get_db
from app.models.notify import NotifyChannel, NotifyPolicy
from app.schemas.notify import (
    NotifyChannelCreate,
    NotifyChannelResponse,
    NotifyChannelTestRequest,
    NotifyPolicyCreate,
    NotifyPolicyResponse,
)
from app.services.notifier import send_channel_test_message

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


@router.post("/channels/{channel_id}/test")
async def test_channel(
    channel_id: int,
    payload: NotifyChannelTestRequest,
    db: Session = Depends(get_db),
    _=Depends(require_template_manager),
):
    channel = db.get(NotifyChannel, channel_id)
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="\u901a\u77e5\u901a\u9053\u4e0d\u5b58\u5728")
    if not channel.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="\u901a\u77e5\u901a\u9053\u5df2\u7981\u7528\uff0c\u65e0\u6cd5\u6d4b\u8bd5"
        )

    content = (payload.content or "").strip() or "\u3010FSU v0.2\u3011\u8fd9\u662f\u4e00\u6761\u901a\u77e5\u901a\u9053\u6d4b\u8bd5\u6d88\u606f"
    success, detail = await send_channel_test_message(channel, content)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"\u6d4b\u8bd5\u53d1\u9001\u5931\u8d25: {detail}",
        )
    return {"ok": True, "detail": detail}


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
