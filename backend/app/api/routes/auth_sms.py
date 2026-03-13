from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token
from app.db.session import get_db
from app.integrations.unisms.client import UniSmsClientError
from app.integrations.unisms.error_mapping import map_unisms_error
from app.schemas.auth_sms import (
    SmsLoginRequest,
    SmsLoginResponse,
    SmsSendCodeRequest,
    SmsSendCodeResponse,
    SmsSendRequest,
    SmsSendResponse,
)
from app.services.auth_sms_login_service import login_by_sms_code
from app.services.auth_sms_service import send_login_code
from app.services.auth_sms import (
    USER_STATUS_DISABLED,
    activate_user_if_needed,
    build_login_user_summary,
    check_send_rate_limit,
    create_and_send_code,
    find_user_by_phone,
    is_user_locked,
    normalize_phone,
    unlock_user_if_expired,
    verify_login_code,
)

router = APIRouter(prefix="/auth/sms", tags=["auth"])


@router.post("/send-code", response_model=SmsSendCodeResponse)
def send_sms_code_v2(
    payload: SmsSendCodeRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    if settings.sms_provider.lower() != "unisms" or not settings.unisms_enabled:
        phone_country_code, phone = normalize_phone(payload.phone_country_code, payload.phone)
        response = SmsSendCodeResponse(resend_after_seconds=settings.sms_send_interval_seconds)
        user = find_user_by_phone(db, phone_country_code, phone)
        if user is None:
            return response
        if unlock_user_if_expired(user):
            db.commit()
        if user.status == USER_STATUS_DISABLED or is_user_locked(user):
            return response
        try:
            check_send_rate_limit(db, phone_country_code, phone, request.client.host if request.client else None)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
        request_id, _debug_code = create_and_send_code(
            db,
            user=user,
            phone_country_code=phone_country_code,
            phone=phone,
            client_ip=request.client.host if request.client else None,
            client_device_id=request.headers.get("X-Device-Id"),
        )
        db.commit()
        response.request_id = request_id
        return response

    try:
        result = send_login_code(
            db,
            phone_country_code=payload.phone_country_code,
            phone=payload.phone,
            client_ip=request.client.host if request.client else None,
            user_agent=request.headers.get("User-Agent"),
            device_id=request.headers.get("X-Device-Id"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except UniSmsClientError as exc:
        internal_code = map_unisms_error(exc.code)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"短信发送失败：{internal_code}",
        ) from exc
    return SmsSendCodeResponse(request_id=result.request_id, resend_after_seconds=result.resend_after_seconds)


@router.post("/send", response_model=SmsSendResponse)
def send_sms_code_legacy(
    payload: SmsSendRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    if settings.sms_provider.lower() != "unisms" or not settings.unisms_enabled:
        phone_country_code, phone = normalize_phone(payload.phone_country_code, payload.phone)
        response = SmsSendResponse(resend_after_seconds=settings.sms_send_interval_seconds)
        user = find_user_by_phone(db, phone_country_code, phone)
        if user is None:
            return response
        if unlock_user_if_expired(user):
            db.commit()
        if user.status == USER_STATUS_DISABLED or is_user_locked(user):
            return response
        try:
            check_send_rate_limit(db, phone_country_code, phone, request.client.host if request.client else None)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
        request_id, debug_code = create_and_send_code(
            db,
            user=user,
            phone_country_code=phone_country_code,
            phone=phone,
            client_ip=request.client.host if request.client else None,
            client_device_id=request.headers.get("X-Device-Id"),
        )
        db.commit()
        response.request_id = request_id
        response.debug_code = debug_code
        return response

    response = send_sms_code_v2(SmsSendCodeRequest(phone_country_code=payload.phone_country_code, phone=payload.phone), request, db)
    return SmsSendResponse(**response.model_dump(), debug_code=None)


@router.post("/login", response_model=SmsLoginResponse)
def login_by_sms(payload: SmsLoginRequest, db: Session = Depends(get_db)):
    if settings.sms_provider.lower() != "unisms" or not settings.unisms_enabled:
        phone_country_code, phone = normalize_phone(payload.phone_country_code, payload.phone)
        user = find_user_by_phone(db, phone_country_code, phone)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="手机号或验证码错误")
        if unlock_user_if_expired(user):
            db.flush()
        if user.status == USER_STATUS_DISABLED:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已停用，请联系管理员")
        if is_user_locked(user):
            raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="账号已锁定，请稍后再试")
        try:
            verify_login_code(db, user=user, phone_country_code=phone_country_code, phone=phone, code=payload.code)
        except ValueError as exc:
            db.commit()
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
        first_login_activated = activate_user_if_needed(user)
        user.last_login_at = datetime.now(timezone.utc)
        token = create_access_token(subject=user.username)
        summary = build_login_user_summary(db, user, first_login_activated=first_login_activated)
        db.commit()
        return SmsLoginResponse(
            access_token=token,
            expires_in=settings.access_token_expire_minutes * 60,
            user=summary,
        )

    return login_by_sms_code(
        db,
        phone_country_code=payload.phone_country_code,
        phone=payload.phone,
        code=payload.code,
    )
