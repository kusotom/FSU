from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User
from app.services.access_control import AccessContext, build_access_context

auth_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(auth_scheme),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或令牌丢失")
    payload = decode_access_token(credentials.credentials)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="令牌无效或已过期")
    user = db.scalar(select(User).where(User.username == payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不可用")
    return user


def get_access_context(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AccessContext:
    return build_access_context(db, user)


def require_admin(
    user: User = Depends(get_current_user),
    access: AccessContext = Depends(get_access_context),
) -> User:
    if not access.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅管理员可操作")
    return user


def require_template_manager(
    user: User = Depends(get_current_user),
    access: AccessContext = Depends(get_access_context),
) -> User:
    if not access.can_manage_templates:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅具备模板管理权限的用户可操作")
    return user


def require_strategy_manager(
    user: User = Depends(get_current_user),
    access: AccessContext = Depends(get_access_context),
) -> User:
    if not access.can_edit_tenant_strategy:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅具备策略管理权限的用户可操作")
    return user


def require_strategy_viewer(
    user: User = Depends(get_current_user),
    access: AccessContext = Depends(get_access_context),
) -> User:
    if not access.can_view_tenant_strategy:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅具备策略查看权限的用户可查看")
    return user
