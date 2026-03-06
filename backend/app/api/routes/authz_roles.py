from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_db
from app.models.user import Role, RolePermission
from app.schemas.authz import RolePermissionBindRequest, RolePermissionBindResponse
from app.services.access_control import PERMISSION_KEY_SET, get_role_permissions

router = APIRouter(prefix="/authz/roles", tags=["authz-roles"])


@router.put("/{role_id}/permissions", response_model=RolePermissionBindResponse)
def bind_role_permissions(
    role_id: int,
    payload: RolePermissionBindRequest,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="角色不存在")

    permission_keys = sorted({str(item or "").strip() for item in payload.permission_keys if str(item or "").strip()})
    invalid = [item for item in permission_keys if item not in PERMISSION_KEY_SET]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"存在未定义的功能权限：{'、'.join(invalid)}",
        )

    role.permissions.clear()
    db.flush()
    for key in permission_keys:
        db.add(RolePermission(role_id=role.id, permission_key=key))
    db.commit()
    db.refresh(role)
    return RolePermissionBindResponse(role_name=role.name, permissions=sorted(get_role_permissions(role)))
