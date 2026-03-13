import hashlib
import logging
import random
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.auth_sms import SmsCodeLog
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.auth_sms import SmsLoginUserSummary
from app.services.access_control import build_access_context

logger = logging.getLogger(__name__)

SMS_SCENE_LOGIN = "LOGIN"
SMS_STATUS_PENDING = "PENDING"
SMS_STATUS_USED = "USED"
SMS_STATUS_EXPIRED = "EXPIRED"
SMS_STATUS_INVALID = "INVALID"
USER_STATUS_PENDING = "PENDING"
USER_STATUS_ACTIVE = "ACTIVE"
USER_STATUS_DISABLED = "DISABLED"
USER_STATUS_LOCKED = "LOCKED"


def normalize_phone(phone_country_code: str | None, phone: str | None) -> tuple[str, str]:
    country_code = str(phone_country_code or "+86").strip() or "+86"
    normalized_phone = "".join(ch for ch in str(phone or "").strip() if ch.isdigit())
    return country_code, normalized_phone


def find_user_by_phone(db: Session, phone_country_code: str, phone: str) -> User | None:
    return db.scalar(
        select(User).where(
            User.phone_country_code == phone_country_code,
            User.phone == phone,
            User.is_active.is_(True),
        )
    )


def is_user_locked(user: User | None, now: datetime | None = None) -> bool:
    if user is None:
        return False
    now = now or datetime.now(timezone.utc)
    if user.status != USER_STATUS_LOCKED:
        return False
    if user.locked_until is None:
        return True
    locked_until = ensure_aware(user.locked_until)
    return locked_until > now


def unlock_user_if_expired(user: User | None) -> bool:
    if user is None or user.status != USER_STATUS_LOCKED or user.locked_until is None:
        return False
    now = datetime.now(timezone.utc)
    locked_until = ensure_aware(user.locked_until)
    if locked_until > now:
        return False
    user.status = USER_STATUS_ACTIVE if user.phone_verified_at or user.activated_at else USER_STATUS_PENDING
    user.locked_until = None
    user.login_fail_count = 0
    return True


def check_send_rate_limit(db: Session, phone_country_code: str, phone: str, client_ip: str | None = None) -> None:
    now = datetime.now(timezone.utc)
    interval_since = now - timedelta(seconds=settings.sms_send_interval_seconds)
    recent = db.scalar(
        select(SmsCodeLog)
        .where(
            SmsCodeLog.phone_country_code == phone_country_code,
            SmsCodeLog.phone == phone,
            SmsCodeLog.scene == SMS_SCENE_LOGIN,
            SmsCodeLog.created_at >= interval_since,
        )
        .order_by(SmsCodeLog.created_at.desc())
    )
    if recent is not None:
        raise ValueError(f"验证码发送过于频繁，请 {settings.sms_send_interval_seconds} 秒后重试")

    ten_minutes_ago = now - timedelta(minutes=10)
    recent_count = len(
        db.scalars(
            select(SmsCodeLog.id).where(
                SmsCodeLog.phone_country_code == phone_country_code,
                SmsCodeLog.phone == phone,
                SmsCodeLog.scene == SMS_SCENE_LOGIN,
                SmsCodeLog.created_at >= ten_minutes_ago,
            )
        ).all()
    )
    if recent_count >= settings.sms_send_limit_per_10m:
        raise ValueError("验证码发送次数过多，请稍后再试")


def create_and_send_code(
    db: Session,
    *,
    user: User,
    phone_country_code: str,
    phone: str,
    client_ip: str | None = None,
    client_device_id: str | None = None,
) -> tuple[str, str | None]:
    now = datetime.now(timezone.utc)
    code = _make_code()
    request_id = uuid4().hex
    log = SmsCodeLog(
        request_id=request_id,
        scene=SMS_SCENE_LOGIN,
        phone_country_code=phone_country_code,
        phone=phone,
        user_id=user.id,
        tenant_id=_resolve_tenant_id(user),
        code_hash=_hash_code(phone_country_code, phone, code),
        expires_at=now + timedelta(seconds=settings.sms_code_expire_seconds),
        send_status="SUCCESS",
        verify_status=SMS_STATUS_PENDING,
        client_ip=client_ip,
        client_device_id=client_device_id,
        sms_vendor="mock" if not settings.sms_tencent_enabled else "tencent",
        created_at=now,
        sent_at=now,
    )
    db.add(log)
    logger.info("sms login code issued phone=%s%s request_id=%s code=%s", phone_country_code, phone, request_id, code)
    debug_code = code if settings.debug or not settings.sms_tencent_enabled else None
    return request_id, debug_code


def verify_login_code(db: Session, *, user: User, phone_country_code: str, phone: str, code: str) -> SmsCodeLog:
    now = datetime.now(timezone.utc)
    log = db.scalar(
        select(SmsCodeLog)
        .where(
            SmsCodeLog.phone_country_code == phone_country_code,
            SmsCodeLog.phone == phone,
            SmsCodeLog.scene == SMS_SCENE_LOGIN,
            SmsCodeLog.verify_status == SMS_STATUS_PENDING,
        )
        .order_by(SmsCodeLog.created_at.desc())
    )
    if log is None:
        raise ValueError("验证码错误或已失效")

    if ensure_aware(log.expires_at) <= now:
        log.verify_status = SMS_STATUS_EXPIRED
        raise ValueError("验证码已过期")

    if log.attempt_count >= settings.sms_verify_max_attempts:
        log.verify_status = SMS_STATUS_INVALID
        raise ValueError("验证码错误次数过多，请重新获取")

    expected_hash = _hash_code(phone_country_code, phone, code)
    if expected_hash != log.code_hash:
        log.attempt_count += 1
        user.login_fail_count = (user.login_fail_count or 0) + 1
        if log.attempt_count >= settings.sms_verify_max_attempts:
            log.verify_status = SMS_STATUS_INVALID
        if user.login_fail_count >= settings.sms_login_fail_lock_threshold:
            user.status = USER_STATUS_LOCKED
            user.locked_until = now + timedelta(minutes=settings.sms_login_lock_minutes)
        raise ValueError("验证码错误或已失效")

    log.verify_status = SMS_STATUS_USED
    log.verified_at = now
    user.login_fail_count = 0
    user.locked_until = None
    return log


def activate_user_if_needed(user: User) -> bool:
    now = datetime.now(timezone.utc)
    activated = False
    if user.status == USER_STATUS_PENDING:
        user.status = USER_STATUS_ACTIVE
        activated = True
    if user.phone_verified_at is None:
        user.phone_verified_at = now
    if activated and user.activated_at is None:
        user.activated_at = now
    return activated


def build_login_user_summary(db: Session, user: User, *, first_login_activated: bool = False) -> SmsLoginUserSummary:
    access = build_access_context(db, user)
    tenant_id, tenant_code = _resolve_tenant_view(user)
    return SmsLoginUserSummary(
        id=user.id,
        username=user.username,
        phone=f"{user.phone_country_code}{user.phone or ''}",
        full_name=user.full_name,
        status=user.status,
        role=access.core_role,
        tenant_id=tenant_id,
        tenant_code=tenant_code,
        first_login_activated=first_login_activated,
    )


def ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _make_code() -> str:
    lower = 10 ** (settings.sms_code_length - 1)
    upper = (10**settings.sms_code_length) - 1
    return str(random.randint(lower, upper))


def _hash_code(phone_country_code: str, phone: str, code: str) -> str:
    raw = f"{settings.secret_key}|{phone_country_code}|{phone}|{code}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _resolve_tenant_id(user: User) -> int | None:
    binding = next((item for item in user.tenant_roles if item.tenant_id), None)
    return binding.tenant_id if binding else None


def _resolve_tenant_view(user: User) -> tuple[int | None, str | None]:
    binding = next((item for item in user.tenant_roles if item.tenant_id and item.tenant), None)
    if binding is not None:
        return binding.tenant_id, binding.tenant.code
    tenant_scope = next((item for item in user.data_scopes if item.scope_type == "tenant"), None)
    if tenant_scope is None:
        return None, None
    tenant = next((item.tenant for item in user.tenant_roles if item.tenant and item.tenant.code == tenant_scope.scope_value), None)
    if isinstance(tenant, Tenant):
        return tenant.id, tenant.code
    return None, tenant_scope.scope_value
