from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.unisms.client import UniSmsClient, UniSmsClientError
from app.models.auth_sms import AuthSmsCode, AuthSmsDeliveryLog
from app.models.user import User
from app.services.auth_sms import USER_STATUS_DISABLED, is_user_locked, normalize_phone, unlock_user_if_expired

logger = logging.getLogger(__name__)


@dataclass
class SmsSendCodeResult:
    request_id: str
    resend_after_seconds: int
    accepted: bool = True


def send_login_code(
    db: Session,
    *,
    phone_country_code: str,
    phone: str,
    client_ip: str | None,
    user_agent: str | None,
    device_id: str | None,
) -> SmsSendCodeResult:
    normalized_country_code, normalized_phone = normalize_phone(phone_country_code, phone)
    phone_e164 = f"{normalized_country_code}{normalized_phone}"
    fallback_request_id = secrets.token_hex(16)

    user = db.scalar(
        select(User).where(
            User.phone_country_code == normalized_country_code,
            User.phone == normalized_phone,
            User.is_active.is_(True),
            User.phone_login_enabled.is_(True),
        )
    )
    if user is None:
        return SmsSendCodeResult(
            request_id=fallback_request_id,
            resend_after_seconds=settings.sms_send_interval_seconds,
        )

    if unlock_user_if_expired(user):
        db.flush()
    if user.status == USER_STATUS_DISABLED or is_user_locked(user):
        db.commit()
        return SmsSendCodeResult(
            request_id=fallback_request_id,
            resend_after_seconds=settings.sms_send_interval_seconds,
        )

    _enforce_send_limit(db, phone_e164=phone_e164, client_ip=client_ip)

    plain_code = "".join(secrets.choice("0123456789") for _ in range(settings.sms_code_length))
    code_salt = secrets.token_hex(16)
    code_hash = hashlib.sha256(f"{settings.secret_key}:{code_salt}:{plain_code}".encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)
    request_id = secrets.token_hex(16)
    sms_code = AuthSmsCode(
        request_id=request_id,
        scene="LOGIN",
        user_id=user.id,
        tenant_id=next((item.tenant_id for item in user.tenant_roles if item.tenant_id), None),
        phone_country_code=normalized_country_code,
        phone=normalized_phone,
        phone_e164=phone_e164,
        code_hash=code_hash,
        code_salt=code_salt,
        code_length=settings.sms_code_length,
        send_status="INIT",
        verify_status="PENDING",
        verify_fail_count=0,
        max_verify_fail_count=settings.sms_verify_max_attempts,
        expires_at=now + timedelta(seconds=settings.sms_code_expire_seconds),
        client_ip=client_ip,
        client_user_agent=user_agent,
        client_device_id=device_id,
        provider="unisms",
        provider_template_id=settings.unisms_login_template_id,
        provider_signature=settings.unisms_sms_signature,
        created_at=now,
        updated_at=now,
    )
    db.add(sms_code)
    db.flush()

    try:
        result = UniSmsClient().send_login_code(to_e164=phone_e164, code=plain_code)
    except UniSmsClientError as exc:
        sms_code.send_status = "FAILED"
        sms_code.updated_at = now
        db.add(
            AuthSmsDeliveryLog(
                sms_code_id=sms_code.id,
                provider="unisms",
                provider_message_id=request_id,
                provider_action="sms.message.send",
                phone_e164=phone_e164,
                submit_status="FAILED",
                submit_code=exc.code,
                submit_message=exc.message,
                submit_payload={
                    "templateId": settings.unisms_login_template_id,
                    "signature": settings.unisms_sms_signature,
                },
                submit_response=exc.raw,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
        logger.exception("unisms send failed request_id=%s phone=%s", request_id, _mask_phone(phone_e164))
        raise

    sms_code.send_status = "SENT"
    sms_code.sent_at = now
    sms_code.updated_at = now
    for message in result.messages:
        db.add(
            AuthSmsDeliveryLog(
                sms_code_id=sms_code.id,
                provider="unisms",
                provider_message_id=message.provider_message_id,
                provider_action="sms.message.send",
                phone_e164=message.to,
                submit_status="ACCEPTED",
                submit_code=result.code,
                submit_message=result.message,
                upstream=message.upstream,
                message_count=message.message_count,
                price=message.price,
                currency=message.currency,
                submit_payload={
                    "templateId": settings.unisms_login_template_id,
                    "signature": settings.unisms_sms_signature,
                },
                submit_response=result.raw,
                created_at=now,
                updated_at=now,
            )
        )
    db.commit()
    logger.info("unisms send accepted request_id=%s phone=%s", request_id, _mask_phone(phone_e164))
    return SmsSendCodeResult(request_id=request_id, resend_after_seconds=settings.sms_send_interval_seconds)


def _enforce_send_limit(db: Session, *, phone_e164: str, client_ip: str | None) -> None:
    now = datetime.now(timezone.utc)
    last_record = db.scalar(
        select(AuthSmsCode)
        .where(AuthSmsCode.phone_e164 == phone_e164, AuthSmsCode.scene == "LOGIN")
        .order_by(AuthSmsCode.id.desc())
    )
    if last_record and (now - last_record.created_at).total_seconds() < settings.sms_send_interval_seconds:
        raise ValueError("验证码发送过于频繁，请稍后重试")

    ten_minutes_ago = now - timedelta(minutes=10)
    recent_count = len(
        db.scalars(
            select(AuthSmsCode.id).where(
                AuthSmsCode.phone_e164 == phone_e164,
                AuthSmsCode.scene == "LOGIN",
                AuthSmsCode.created_at >= ten_minutes_ago,
            )
        ).all()
    )
    if recent_count >= settings.sms_send_limit_per_10m:
        raise ValueError("验证码发送次数过多，请稍后再试")

    if client_ip:
        one_minute_ago = now - timedelta(minutes=1)
        one_hour_ago = now - timedelta(hours=1)
        minute_count = len(
            db.scalars(
                select(AuthSmsCode.id).where(
                    AuthSmsCode.client_ip == client_ip,
                    AuthSmsCode.created_at >= one_minute_ago,
                )
            ).all()
        )
        if minute_count >= settings.sms_ip_limit_per_minute:
            raise ValueError("请求过于频繁，请稍后再试")
        hour_count = len(
            db.scalars(
                select(AuthSmsCode.id).where(
                    AuthSmsCode.client_ip == client_ip,
                    AuthSmsCode.created_at >= one_hour_ago,
                )
            ).all()
        )
        if hour_count >= settings.sms_ip_limit_per_hour:
            raise ValueError("请求过于频繁，请稍后再试")


def _mask_phone(phone: str) -> str:
    if len(phone) < 7:
        return phone
    return f"{phone[:3]}****{phone[-4:]}"
