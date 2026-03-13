from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_access_context, get_current_user
from app.core.security import create_access_token, verify_password
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse, UserMeResponse
from app.services.access_control import AccessContext
from app.services.auth_sms import USER_STATUS_DISABLED, is_user_locked, unlock_user_if_expired

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == payload.username))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    if unlock_user_if_expired(user):
        db.commit()
        db.refresh(user)
    if user.status == USER_STATUS_DISABLED or is_user_locked(user):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号不可登录")
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    token = create_access_token(subject=user.username)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserMeResponse)
def me(
    user: User = Depends(get_current_user),
    access: AccessContext = Depends(get_access_context),
):
    return UserMeResponse(
        id=user.id,
        username=user.username,
        phone=f"{user.phone_country_code}{user.phone}" if user.phone else None,
        full_name=user.full_name,
        status=user.status,
        core_role=access.core_role,
        roles=sorted(access.role_names),
        permissions=sorted(access.permissions),
        tenant_codes=sorted(access.tenant_codes),
        tenant_roles=access.tenant_roles,
        scopes=access.data_scopes,
        role_bindings=access.role_bindings,
    )
