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
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="\u672a\u767b\u5f55\u6216\u4ee4\u724c\u4e22\u5931")
    payload = decode_access_token(credentials.credentials)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="\u4ee4\u724c\u65e0\u6548\u6216\u5df2\u8fc7\u671f")
    user = db.scalar(select(User).where(User.username == payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="\u7528\u6237\u4e0d\u53ef\u7528")
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
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="\u4ec5\u7ba1\u7406\u5458\u53ef\u64cd\u4f5c")
    return user


def require_template_manager(
    user: User = Depends(get_current_user),
    access: AccessContext = Depends(get_access_context),
) -> User:
    if not access.can_manage_templates:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="\u4ec5\u603b\u90e8\u76d1\u63a7\u7ec4\u6216\u7ba1\u7406\u5458\u53ef\u64cd\u4f5c")
    return user


def require_strategy_manager(
    user: User = Depends(get_current_user),
    access: AccessContext = Depends(get_access_context),
) -> User:
    if not access.can_edit_tenant_strategy:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅子公司监控组或管理员可操作策略")
    return user


def require_strategy_viewer(
    user: User = Depends(get_current_user),
    access: AccessContext = Depends(get_access_context),
) -> User:
    if not access.can_view_tenant_strategy:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅监控组或管理员可查看策略")
    return user
