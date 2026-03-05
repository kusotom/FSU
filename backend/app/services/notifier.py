from collections.abc import Iterable

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.alarm import AlarmEvent
from app.models.device import FSUDevice, MonitorPoint
from app.models.notify import NotifyChannel, NotifyPolicy
from app.models.site import Site

_EVENT_LABELS = {
    "trigger": "\u89e6\u53d1",
    "recover": "\u6062\u590d",
    "ack": "\u786e\u8ba4",
    "close": "\u5173\u95ed",
}

_STATUS_LABELS = {
    "active": "\u6d3b\u52a8",
    "acknowledged": "\u5df2\u786e\u8ba4",
    "recovered": "\u5df2\u6062\u590d",
    "closed": "\u5df2\u5173\u95ed",
}


def _event_allowed(event_types: str, event_type: str) -> bool:
    allowed = {item.strip() for item in event_types.split(",") if item.strip()}
    return event_type in allowed


async def _post_json(url: str, payload: dict) -> tuple[bool, str]:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=payload)
        if 200 <= resp.status_code < 300:
            return True, f"HTTP {resp.status_code}"
        return False, f"HTTP {resp.status_code}: {resp.text[:180]}"
    except Exception as exc:
        return False, str(exc)


def _webhook_payload(
    event_type: str,
    alarm: AlarmEvent,
    site: Site,
    device: FSUDevice,
    point: MonitorPoint,
) -> dict:
    return {
        "event_type": event_type,
        "event_label": _EVENT_LABELS.get(event_type, event_type),
        "site_code": site.code,
        "site_name": site.name,
        "device_code": device.code,
        "device_name": device.name,
        "point_key": point.point_key,
        "point_name": point.point_name,
        "alarm_id": alarm.id,
        "alarm_code": alarm.alarm_code,
        "alarm_name": alarm.alarm_name,
        "alarm_level": alarm.alarm_level,
        "status": alarm.status,
        "status_label": _STATUS_LABELS.get(alarm.status, alarm.status),
        "trigger_value": alarm.trigger_value,
        "content": alarm.content,
        "started_at": alarm.started_at.isoformat() if alarm.started_at else None,
        "recovered_at": alarm.recovered_at.isoformat() if alarm.recovered_at else None,
    }


def _wechat_robot_payload(
    event_type: str,
    alarm: AlarmEvent,
    site: Site,
    device: FSUDevice,
    point: MonitorPoint,
) -> dict:
    event_label = _EVENT_LABELS.get(event_type, event_type)
    status_label = _STATUS_LABELS.get(alarm.status, alarm.status)
    text = (
        f"[\u52a8\u73af\u544a\u8b66\u901a\u77e5] \u4e8b\u4ef6: {event_label}\n"
        f"\u7ad9\u70b9: {site.name}({site.code})\n"
        f"\u8bbe\u5907: {device.name}({device.code})\n"
        f"\u76d1\u63a7\u9879: {point.point_name}({point.point_key})\n"
        f"\u544a\u8b66: {alarm.alarm_name} L{alarm.alarm_level}\n"
        f"\u72b6\u6001: {status_label}\n"
        f"\u89e6\u53d1\u503c: {alarm.trigger_value}\n"
        f"\u5185\u5bb9: {alarm.content}"
    )
    return {"msgtype": "text", "text": {"content": text}}


async def dispatch_alarm_notifications(
    db: Session,
    event_type: str,
    alarm: AlarmEvent,
    site: Site,
    device: FSUDevice,
    point: MonitorPoint,
) -> list[dict]:
    policies: Iterable[NotifyPolicy] = db.scalars(
        select(NotifyPolicy).where(NotifyPolicy.is_enabled.is_(True))
    ).all()
    channels = {
        item.id: item
        for item in db.scalars(select(NotifyChannel).where(NotifyChannel.is_enabled.is_(True))).all()
    }

    results: list[dict] = []
    for policy in policies:
        if alarm.alarm_level < policy.min_alarm_level:
            continue
        if not _event_allowed(policy.event_types, event_type):
            continue
        channel = channels.get(policy.channel_id)
        if channel is None:
            continue

        if channel.channel_type == "wechat_robot":
            payload = _wechat_robot_payload(event_type, alarm, site, device, point)
        else:
            payload = _webhook_payload(event_type, alarm, site, device, point)

        success, detail = await _post_json(channel.endpoint, payload)
        results.append(
            {
                "policy": policy.name,
                "channel": channel.name,
                "success": success,
                "detail": detail,
            }
        )
    return results
