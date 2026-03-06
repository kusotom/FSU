from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_db
from app.models.site import Site
from app.models.tenant import Tenant
from app.models.user import User, UserDataScope
from app.schemas.authz import UserScopeBindRequest, UserScopeBindResponse
from app.schemas.user import UserDataScopeView
from app.services.access_control import SCOPE_TYPE_SET

router = APIRouter(prefix="/authz/users", tags=["authz-users"])


def _normalize_scopes(db: Session, scopes: list) -> list[UserDataScopeView]:
    normalized: dict[tuple[str, str], UserDataScopeView] = {}
    for item in scopes:
        scope_type = str(item.scope_type or "").strip().lower()
        scope_value = str(item.scope_value or "").strip()
        if scope_type not in SCOPE_TYPE_SET:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"不支持的数据范围类型：{scope_type}")
        if scope_type == "all":
            normalized[("all", "*")] = UserDataScopeView(scope_type="all", scope_value="*", scope_name="全部数据")
            continue
        if not scope_value:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="数据范围值不能为空")
        if scope_type == "tenant":
            tenant = db.scalar(select(Tenant).where(Tenant.code == scope_value))
            if tenant is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"租户不存在：{scope_value}")
            normalized[(scope_type, tenant.code)] = UserDataScopeView(
                scope_type="tenant",
                scope_value=tenant.code,
                scope_name=tenant.name,
            )
            continue
        if scope_type == "site":
            site = db.scalar(select(Site).where(Site.code == scope_value))
            if site is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"站点不存在：{scope_value}")
            normalized[(scope_type, site.code)] = UserDataScopeView(
                scope_type="site",
                scope_value=site.code,
                scope_name=site.name,
            )
            continue
        if scope_type == "region":
            site_exists = db.scalar(select(Site.id).where(Site.region == scope_value).limit(1))
            if site_exists is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"区域不存在：{scope_value}")
            normalized[(scope_type, scope_value)] = UserDataScopeView(
                scope_type="region",
                scope_value=scope_value,
                scope_name=scope_value,
            )
    if not normalized:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请至少配置一个数据范围")
    if ("all", "*") in normalized:
        return [normalized[("all", "*")]]
    return sorted(normalized.values(), key=lambda item: (item.scope_type, item.scope_value))


@router.put("/{user_id}/scopes", response_model=UserScopeBindResponse)
def bind_user_scopes(
    user_id: int,
    payload: UserScopeBindRequest,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    data_scopes = _normalize_scopes(db, payload.data_scopes)
    for item in list(user.data_scopes):
        db.delete(item)
    db.flush()
    for item in data_scopes:
        user.data_scopes.append(
            UserDataScope(
                scope_type=item.scope_type,
                scope_value=item.scope_value,
                scope_name=item.scope_name,
            )
        )
    db.commit()
    db.refresh(user)
    return UserScopeBindResponse(user_id=user.id, data_scopes=data_scopes)
