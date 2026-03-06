from fastapi import Depends, HTTPException, status

from app.api.deps import get_access_context
from app.services.access_control import AccessContext


def permission_required(permission_code: str):
    def _dep(access: AccessContext = Depends(get_access_context)) -> AccessContext:
        if not access.has_permission(permission_code):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"缺少权限：{permission_code}")
        return access

    return _dep


def any_permission_required(permission_codes: list[str]):
    def _dep(access: AccessContext = Depends(get_access_context)) -> AccessContext:
        if not any(access.has_permission(code) for code in permission_codes):
            joined = " / ".join(permission_codes)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"缺少权限：{joined}")
        return access

    return _dep
