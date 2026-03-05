from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_access_context, get_current_user
from app.core.security import create_access_token, verify_password
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse, UserMeResponse
from app.services.access_control import AccessContext

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == payload.username))
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="\u7528\u6237\u540d\u6216\u5bc6\u7801\u9519\u8bef",
        )
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
        full_name=user.full_name,
        roles=sorted(access.role_names),
        is_admin=access.is_admin,
        tenant_codes=sorted(access.tenant_codes),
        is_hq_noc=access.is_hq_noc,
        tenant_roles=access.tenant_roles,
    )
