from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.auth_sms import AuthSmsCode, AuthSmsDeliveryLog


def verify_unisms_dlr_signature(authorization: str | None, payload: dict) -> bool:
    if not settings.unisms_dlr_verify_enabled:
        return True
    if not authorization or not authorization.startswith("UNI1-HMAC-SHA256 "):
        return False

    fields: dict[str, str] = {}
    for part in authorization.replace("UNI1-HMAC-SHA256 ", "").split(","):
        if "=" not in part:
            continue
        key, value = part.strip().split("=", 1)
        fields[key.strip().lower()] = value.strip()

    timestamp = fields.get("timestamp")
    nonce = fields.get("nonce")
    signature = fields.get("signature")
    if not timestamp or not nonce or not signature:
        return False

    try:
        timestamp_dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return False
    now = datetime.now(timezone.utc)
    if abs((now - timestamp_dt).total_seconds()) > 300:
        return False

    sign_payload = dict(payload)
    sign_payload["timestamp"] = timestamp
    sign_payload["nonce"] = nonce
    canonical = urlencode(sorted(sign_payload.items()), doseq=False)
    digest = hmac.new(
        settings.unisms_dlr_secret.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    expected_signature = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected_signature, signature)


def handle_unisms_dlr(
    db: Session,
    *,
    payload: dict,
    authorization: str | None,
    headers: dict,
) -> None:
    if not verify_unisms_dlr_signature(authorization, payload):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid unisms signature")

    provider_message_id = str(payload["id"])
    now = datetime.now(timezone.utc)
    delivery = db.scalar(
        select(AuthSmsDeliveryLog).where(
            AuthSmsDeliveryLog.provider == "unisms",
            AuthSmsDeliveryLog.provider_message_id == provider_message_id,
        )
    )
    if delivery is None:
        delivery = AuthSmsDeliveryLog(
            provider="unisms",
            provider_message_id=provider_message_id,
            provider_action="sms.message.send",
            phone_e164=str(payload.get("to", "")),
            submit_status="ACCEPTED",
            created_at=now,
            updated_at=now,
        )
        db.add(delivery)
        db.flush()

    delivery.dlr_status = payload.get("status")
    delivery.dlr_error_code = payload.get("errorCode")
    delivery.dlr_error_message = payload.get("errorMessage")
    delivery.message_count = payload.get("messageCount")
    delivery.currency = payload.get("currency")
    delivery.submit_date = _parse_datetime(payload.get("submitDate"))
    delivery.done_date = _parse_datetime(payload.get("doneDate"))
    delivery.raw_webhook_payload = payload
    delivery.raw_webhook_headers = headers
    delivery.webhook_verified = True
    delivery.webhook_received_at = now
    delivery.updated_at = now

    sms_code = db.get(AuthSmsCode, delivery.sms_code_id) if delivery.sms_code_id else None
    if sms_code is not None:
        sms_code.updated_at = now
        status_value = str(payload.get("status", "")).lower()
        if status_value == "delivered":
            sms_code.send_status = "DELIVERED"
        elif status_value:
            sms_code.send_status = "FAILED"

    db.commit()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
