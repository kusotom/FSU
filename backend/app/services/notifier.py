from collections.abc import Iterable
import asyncio
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.alarm import AlarmEvent
from app.models.device import FSUDevice, MonitorPoint
from app.models.notify import NotifyChannel, NotifyPolicy
from app.models.site import Site

_EVENT_LABELS = {
    "trigger": "触发",
    "recover": "恢复",
    "ack": "确认",
    "close": "关闭",
}

_STATUS_LABELS = {
    "active": "活动",
    "acknowledged": "已确认",
    "recovered": "已恢复",
    "closed": "已关闭",
}

_SMS_TENCENT_HOST = "sms.tencentcloudapi.com"
_SMS_TENCENT_ENDPOINT = "https://sms.tencentcloudapi.com"
_SMS_TENCENT_ACTION = "SendSms"
_SMS_TENCENT_VERSION = "2021-01-11"
_SMS_TENCENT_SERVICE = "sms"


def _event_allowed(event_types: str, event_type: str) -> bool:
    allowed = {item.strip() for item in event_types.split(",") if item.strip()}
    return event_type in allowed


def _trim_text(value: str, limit: int = 1800) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: limit - 12]}...(truncated)"


def _parse_wechat_robot_result(resp: httpx.Response) -> tuple[bool, str]:
    try:
        data = resp.json()
    except Exception:
        return False, f"HTTP {resp.status_code}: invalid JSON response"
    errcode = data.get("errcode")
    errmsg = str(data.get("errmsg", "")).strip()
    if errcode in (0, "0", None):
        return True, f"HTTP {resp.status_code}: ok"
    return False, f"HTTP {resp.status_code}: errcode={errcode} errmsg={errmsg or '-'}"


def _normalize_phone_number(value: str) -> str | None:
    raw = value.strip().replace(" ", "").replace("-", "")
    if not raw:
        return None
    if raw.startswith("00") and raw[2:].isdigit():
        raw = f"+{raw[2:]}"
    if raw.startswith("+"):
        if raw[1:].isdigit() and 6 <= len(raw[1:]) <= 20:
            return raw
        return None
    if raw.isdigit():
        if len(raw) == 11 and raw.startswith("1"):
            return f"+86{raw}"
        if 6 <= len(raw) <= 20:
            return f"+{raw}"
    return None


def _parse_sms_phone_numbers(raw: str) -> list[str]:
    result = []
    for item in str(raw or "").split(","):
        phone = _normalize_phone_number(item)
        if phone:
            result.append(phone)
    return list(dict.fromkeys(result))


def _sms_template_params(
    message: str,
    *,
    event_type: str | None = None,
    alarm: AlarmEvent | None = None,
    site: Site | None = None,
    device: FSUDevice | None = None,
    point: MonitorPoint | None = None,
) -> list[str]:
    mode = str(settings.sms_tencent_template_mode or "single_text").strip().lower()
    if mode != "alarm_v6":
        return [_trim_text(message, 70)]

    if alarm is None or site is None or device is None or point is None:
        return ["测试", "测试站点", "测试设备", "测试监控项", "L1", _trim_text(message, 20)]

    event_label = _EVENT_LABELS.get(event_type or "", event_type or "告警")
    status_label = _STATUS_LABELS.get(alarm.status, alarm.status)
    return [
        _trim_text(event_label, 8),
        _trim_text(site.name, 16),
        _trim_text(device.name, 16),
        _trim_text(point.point_name, 16),
        f"L{alarm.alarm_level}",
        _trim_text(status_label, 12),
    ]


def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _build_tencent_sms_headers(payload: str) -> dict:
    timestamp = int(time.time())
    date = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")
    content_type = "application/json; charset=utf-8"
    signed_headers = "content-type;host"

    hashed_payload = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    canonical_request = (
        "POST\n/\n\n"
        f"content-type:{content_type}\n"
        f"host:{_SMS_TENCENT_HOST}\n\n"
        f"{signed_headers}\n"
        f"{hashed_payload}"
    )
    credential_scope = f"{date}/{_SMS_TENCENT_SERVICE}/tc3_request"
    string_to_sign = (
        "TC3-HMAC-SHA256\n"
        f"{timestamp}\n"
        f"{credential_scope}\n"
        f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
    )

    secret_date = _hmac_sha256(f"TC3{settings.sms_tencent_secret_key}".encode("utf-8"), date)
    secret_service = _hmac_sha256(secret_date, _SMS_TENCENT_SERVICE)
    secret_signing = _hmac_sha256(secret_service, "tc3_request")
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = (
        "TC3-HMAC-SHA256 "
        f"Credential={settings.sms_tencent_secret_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    return {
        "Authorization": authorization,
        "Content-Type": content_type,
        "Host": _SMS_TENCENT_HOST,
        "X-TC-Action": _SMS_TENCENT_ACTION,
        "X-TC-Version": _SMS_TENCENT_VERSION,
        "X-TC-Region": settings.sms_tencent_region,
        "X-TC-Timestamp": str(timestamp),
    }


def _parse_tencent_sms_result(resp: httpx.Response) -> tuple[bool, str]:
    try:
        data = resp.json()
    except Exception:
        return False, f"HTTP {resp.status_code}: invalid JSON response"

    body = data.get("Response", {})
    err = body.get("Error")
    if err:
        code = err.get("Code", "-")
        message = err.get("Message", "")
        return False, f"HTTP {resp.status_code}: {code} {message}"

    statuses = body.get("SendStatusSet", []) or []
    failed = [item for item in statuses if item.get("Code") != "Ok"]
    if failed:
        item = failed[0]
        return False, f"HTTP {resp.status_code}: {item.get('Code')} {item.get('Message', '')}".strip()

    req_id = body.get("RequestId", "-")
    return True, f"HTTP {resp.status_code}: ok request_id={req_id}"


async def _post_json(url: str, payload: dict, *, channel_type: str) -> tuple[bool, str]:
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(url, json=payload)

            if channel_type == "wechat_robot":
                return _parse_wechat_robot_result(resp)

            if 200 <= resp.status_code < 300:
                return True, f"HTTP {resp.status_code}"
            if resp.status_code >= 500 and attempt < max_retries:
                await asyncio.sleep(0.2 * (attempt + 1))
                continue
            return False, f"HTTP {resp.status_code}: {resp.text[:180]}"
        except Exception as exc:
            if attempt < max_retries:
                await asyncio.sleep(0.2 * (attempt + 1))
                continue
            return False, str(exc)
    return False, "unknown error"


def _validate_tencent_sms_settings() -> str | None:
    if not settings.sms_tencent_enabled:
        return "SMS_TENCENT_ENABLED=false"
    missing = []
    if not settings.sms_tencent_secret_id:
        missing.append("SMS_TENCENT_SECRET_ID")
    if not settings.sms_tencent_secret_key:
        missing.append("SMS_TENCENT_SECRET_KEY")
    if not settings.sms_tencent_sdk_app_id:
        missing.append("SMS_TENCENT_SDK_APP_ID")
    if not settings.sms_tencent_sign_name:
        missing.append("SMS_TENCENT_SIGN_NAME")
    if not settings.sms_tencent_template_id:
        missing.append("SMS_TENCENT_TEMPLATE_ID")
    if missing:
        return f"missing env: {', '.join(missing)}"
    return None


async def _send_tencent_sms(
    phone_numbers: list[str],
    message: str,
    *,
    event_type: str | None = None,
    alarm: AlarmEvent | None = None,
    site: Site | None = None,
    device: FSUDevice | None = None,
    point: MonitorPoint | None = None,
) -> tuple[bool, str]:
    setting_error = _validate_tencent_sms_settings()
    if setting_error:
        return False, setting_error
    if not phone_numbers:
        return False, "no valid phone numbers"

    template_params = _sms_template_params(
        message,
        event_type=event_type,
        alarm=alarm,
        site=site,
        device=device,
        point=point,
    )
    body = {
        "SmsSdkAppId": settings.sms_tencent_sdk_app_id,
        "SignName": settings.sms_tencent_sign_name,
        "TemplateId": settings.sms_tencent_template_id,
        "PhoneNumberSet": phone_numbers,
        "TemplateParamSet": template_params,
    }
    body_text = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    headers = _build_tencent_sms_headers(body_text)

    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(_SMS_TENCENT_ENDPOINT, headers=headers, content=body_text.encode("utf-8"))
            ok, detail = _parse_tencent_sms_result(resp)
            if ok:
                return ok, detail
            if resp.status_code >= 500 and attempt < max_retries:
                await asyncio.sleep(0.2 * (attempt + 1))
                continue
            return ok, detail
        except Exception as exc:
            if attempt < max_retries:
                await asyncio.sleep(0.2 * (attempt + 1))
                continue
            return False, str(exc)
    return False, "unknown error"


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
        f"[动环告警通知] 事件: {event_label}\n"
        f"站点: {site.name}({site.code})\n"
        f"设备: {device.name}({device.code})\n"
        f"监控项: {point.point_name}({point.point_key})\n"
        f"告警: {alarm.alarm_name} L{alarm.alarm_level}\n"
        f"状态: {status_label}\n"
        f"触发值: {alarm.trigger_value}\n"
        f"内容: {alarm.content}"
    )
    return {"msgtype": "text", "text": {"content": _trim_text(text)}}


def _sms_text_payload(
    event_type: str,
    alarm: AlarmEvent,
    site: Site,
    device: FSUDevice,
    point: MonitorPoint,
) -> str:
    event_label = _EVENT_LABELS.get(event_type, event_type)
    return _trim_text(
        f"[FSU] {event_label} L{alarm.alarm_level} 站点:{site.name} 设备:{device.name} 监控项:{point.point_name} 内容:{alarm.content}",
        120,
    )


def _channel_test_payload(channel_type: str, content: str) -> dict:
    if channel_type == "wechat_robot":
        return {"msgtype": "text", "text": {"content": _trim_text(content)}}
    return {"event_type": "test", "message": content}


async def send_channel_test_message(channel: NotifyChannel, content: str) -> tuple[bool, str]:
    if channel.channel_type == "sms_tencent":
        phones = _parse_sms_phone_numbers(channel.endpoint)
        return await _send_tencent_sms(phones, content)
    payload = _channel_test_payload(channel.channel_type, content)
    return await _post_json(channel.endpoint, payload, channel_type=channel.channel_type)


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
            success, detail = await _post_json(channel.endpoint, payload, channel_type=channel.channel_type)
        elif channel.channel_type == "sms_tencent":
            sms_text = _sms_text_payload(event_type, alarm, site, device, point)
            phones = _parse_sms_phone_numbers(channel.endpoint)
            success, detail = await _send_tencent_sms(
                phones,
                sms_text,
                event_type=event_type,
                alarm=alarm,
                site=site,
                device=device,
                point=point,
            )
        else:
            payload = _webhook_payload(event_type, alarm, site, device, point)
            success, detail = await _post_json(channel.endpoint, payload, channel_type=channel.channel_type)

        results.append(
            {
                "policy": policy.name,
                "channel": channel.name,
                "success": success,
                "detail": detail,
            }
        )
    return results
