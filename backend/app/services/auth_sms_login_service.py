from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token
from app.models.auth_sms import AuthSmsCode
from app.models.user import User
from app.schemas.auth_sms import SmsLoginResponse
from app.services.access_control import build_access_context
from app.services.auth_sms import (
    USER_STATUS_ACTIVE,
    USER_STATUS_DISABLED,
    USER_STATUS_LOCKED,
    USER_STATUS_PENDING,
    build_login_user_summary,
    is_user_locked,
    normalize_phone,
    unlock_user_if_expired,
)


def login_by_sms_code(
    db: Session,
    *,
    phone_country_code: str,
    phone: str,
    code: str,
) -> SmsLoginResponse:
    normalized_country_code, normalized_phone = normalize_phone(phone_country_code, phone)
    phone_e164 = f"{normalized_country_code}{normalized_phone}"
    user = db.scalar(
        select(User).where(
            User.phone_country_code == normalized_country_code,
            User.phone == normalized_phone,
            User.is_active.is_(True),
            User.phone_login_enabled.is_(True),
        )
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="手机号或验证码错误")

    if unlock_user_if_expired(user):
        db.flush()
    if user.status == USER_STATUS_DISABLED:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已停用，请联系管理员")
    if is_user_locked(user):
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="账号已锁定，请稍后再试")

    now = datetime.now(timezone.utc)
    sms_code = db.scalar(
        select(AuthSmsCode)
        .where(
            AuthSmsCode.phone_e164 == phone_e164,
            AuthSmsCode.scene == "LOGIN",
            AuthSmsCode.verify_status == "PENDING",
        )
        .order_by(AuthSmsCode.id.desc())
    )
    if sms_code is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="手机号或验证码错误")

    if sms_code.expires_at <= now:
        sms_code.verify_status = "EXPIRED"
        sms_code.updated_at = now
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="验证码已过期")

    if sms_code.verify_fail_count >= sms_code.max_verify_fail_count:
        sms_code.verify_status = "INVALID"
        sms_code.updated_at = now
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="验证码错误次数过多，请重新获取")

    expected_hash = hashlib.sha256(
        f"{settings.secret_key}:{sms_code.code_salt}:{code}".encode("utf-8")
    ).hexdigest()
    if expected_hash != sms_code.code_hash:
        sms_code.verify_fail_count += 1
        sms_code.updated_at = now
        user.login_fail_count = (user.login_fail_count or 0) + 1
        if sms_code.verify_fail_count >= sms_code.max_verify_fail_count:
            sms_code.verify_status = "INVALID"
        if user.login_fail_count >= settings.sms_login_fail_lock_threshold:
            user.status = USER_STATUS_LOCKED
            user.locked_until = now + timedelta(minutes=settings.sms_login_lock_minutes)
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="手机号或验证码错误")

    sms_code.verify_status = "USED"
    sms_code.used_at = now
    sms_code.updated_at = now
    user.login_fail_count = 0
    user.locked_until = None
    if user.phone_verified_at is None:
        user.phone_verified_at = now
    first_login_activated = False
    if user.status == USER_STATUS_PENDING:
        user.status = USER_STATUS_ACTIVE
        user.activated_at = user.activated_at or now
        first_login_activated = True
    user.last_login_at = now

    token = create_access_token(subject=user.username)
    summary = build_login_user_summary(db, user, first_login_activated=first_login_activated)
    db.commit()
    return SmsLoginResponse(
        access_token=token,
        expires_in=settings.access_token_expire_minutes * 60,
        user=summary,
    )
