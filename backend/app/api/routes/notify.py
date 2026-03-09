from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps_authz import permission_required
from app.db.session import get_db
from app.models.notify import NotifyChannel, NotifyPolicy
from app.schemas.notify import (
    NotifyChannelCreate,
    NotifyChannelResponse,
    NotifyChannelTestRequest,
    NotifyChannelUpdate,
    NotifyPolicyCreate,
    NotifyPolicyResponse,
    NotifyPolicyUpdate,
)
from app.services.notifier import send_channel_test_message

router = APIRouter(prefix="/notify", tags=["notify"])


def _policy_channel_ids(policy: NotifyPolicy) -> list[int]:
    raw = str(getattr(policy, "channel_ids", "") or "").strip()
    if raw:
        result = []
        for item in raw.split(","):
            token = item.strip()
            if token.isdigit():
                channel_id = int(token)
                if channel_id not in result:
                    result.append(channel_id)
        if result:
            return result
    if policy.channel_id:
        return [policy.channel_id]
    return []


def _join_channel_ids(channel_ids: list[int]) -> str:
    return ",".join(str(item) for item in channel_ids)


def _policy_to_response(policy: NotifyPolicy) -> dict:
    return {
        "id": policy.id,
        "name": policy.name,
        "channel_id": policy.channel_id,
        "channel_ids": _policy_channel_ids(policy),
        "min_alarm_level": policy.min_alarm_level,
        "event_types": policy.event_types,
        "is_enabled": policy.is_enabled,
        "created_at": policy.created_at,
    }


def _get_channel_or_404(db: Session, channel_id: int) -> NotifyChannel:
    channel = db.get(NotifyChannel, channel_id)
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="通知通道不存在")
    return channel


def _get_policy_or_404(db: Session, policy_id: int) -> NotifyPolicy:
    policy = db.get(NotifyPolicy, policy_id)
    if policy is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="通知策略不存在")
    return policy


@router.get("/channels", response_model=list[NotifyChannelResponse])
def list_channels(
    db: Session = Depends(get_db),
    _=Depends(permission_required("notify.channel.view")),
):
    return list(db.scalars(select(NotifyChannel).order_by(NotifyChannel.id.desc())).all())


@router.post("/channels", response_model=NotifyChannelResponse)
def create_channel(
    payload: NotifyChannelCreate,
    db: Session = Depends(get_db),
    _=Depends(permission_required("notify.channel.manage")),
):
    exists = db.scalar(select(NotifyChannel).where(NotifyChannel.name == payload.name))
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="通知通道名称已存在")
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
    _=Depends(permission_required("notify.channel.manage")),
):
    channel = _get_channel_or_404(db, channel_id)
    if not channel.is_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="通知通道已禁用，无法测试")

    content = (payload.content or "").strip() or "【FSU v0.21】这是一条通知通道测试消息"
    success, detail = await send_channel_test_message(channel, content)
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"测试发送失败: {detail}")
    return {"ok": True, "detail": detail}


@router.put("/channels/{channel_id}", response_model=NotifyChannelResponse)
def update_channel(
    channel_id: int,
    payload: NotifyChannelUpdate,
    db: Session = Depends(get_db),
    _=Depends(permission_required("notify.channel.manage")),
):
    channel = _get_channel_or_404(db, channel_id)
    exists = db.scalar(select(NotifyChannel).where(NotifyChannel.name == payload.name, NotifyChannel.id != channel_id))
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="通知通道名称已存在")

    channel.name = payload.name
    channel.channel_type = payload.channel_type
    channel.endpoint = payload.endpoint
    if payload.secret is not None:
        channel.secret = payload.secret
    channel.is_enabled = payload.is_enabled
    db.commit()
    db.refresh(channel)
    return channel


@router.delete("/channels/{channel_id}")
def delete_channel(
    channel_id: int,
    db: Session = Depends(get_db),
    _=Depends(permission_required("notify.channel.manage")),
):
    channel = _get_channel_or_404(db, channel_id)
    policies = list(db.scalars(select(NotifyPolicy)).all())
    policy_count = 0
    for policy in policies:
        if channel_id in _policy_channel_ids(policy):
            policy_count += 1
    if policy_count:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="通知通道已被策略引用，无法删除")
    db.delete(channel)
    db.commit()
    return {"ok": True}


@router.get("/policies", response_model=list[NotifyPolicyResponse])
def list_policies(
    db: Session = Depends(get_db),
    _=Depends(permission_required("notify.policy.view")),
):
    rows = list(db.scalars(select(NotifyPolicy).order_by(NotifyPolicy.id.desc())).all())
    return [_policy_to_response(row) for row in rows]


@router.post("/policies", response_model=NotifyPolicyResponse)
def create_policy(
    payload: NotifyPolicyCreate,
    db: Session = Depends(get_db),
    _=Depends(permission_required("notify.policy.manage")),
):
    exists = db.scalar(select(NotifyPolicy).where(NotifyPolicy.name == payload.name))
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="策略名称已存在")
    channels = list(db.scalars(select(NotifyChannel).where(NotifyChannel.id.in_(payload.channel_ids))).all())
    channel_map = {item.id: item for item in channels}
    missing = [item for item in payload.channel_ids if item not in channel_map]
    if missing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="通知通道不存在")

    item = NotifyPolicy(
        name=payload.name,
        channel_id=payload.channel_ids[0],
        channel_ids=_join_channel_ids(payload.channel_ids),
        min_alarm_level=payload.min_alarm_level,
        event_types=payload.event_types,
        is_enabled=payload.is_enabled,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return _policy_to_response(item)


@router.put("/policies/{policy_id}", response_model=NotifyPolicyResponse)
def update_policy(
    policy_id: int,
    payload: NotifyPolicyUpdate,
    db: Session = Depends(get_db),
    _=Depends(permission_required("notify.policy.manage")),
):
    policy = _get_policy_or_404(db, policy_id)
    exists = db.scalar(select(NotifyPolicy).where(NotifyPolicy.name == payload.name, NotifyPolicy.id != policy_id))
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="策略名称已存在")
    channels = list(db.scalars(select(NotifyChannel).where(NotifyChannel.id.in_(payload.channel_ids))).all())
    channel_map = {item.id: item for item in channels}
    missing = [item for item in payload.channel_ids if item not in channel_map]
    if missing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="通知通道不存在")

    policy.name = payload.name
    policy.channel_id = payload.channel_ids[0]
    policy.channel_ids = _join_channel_ids(payload.channel_ids)
    policy.min_alarm_level = payload.min_alarm_level
    policy.event_types = payload.event_types
    policy.is_enabled = payload.is_enabled
    db.commit()
    db.refresh(policy)
    return _policy_to_response(policy)


@router.delete("/policies/{policy_id}")
def delete_policy(
    policy_id: int,
    db: Session = Depends(get_db),
    _=Depends(permission_required("notify.policy.manage")),
):
    policy = _get_policy_or_404(db, policy_id)
    db.delete(policy)
    db.commit()
    return {"ok": True}
