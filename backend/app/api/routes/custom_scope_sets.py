from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.api.deps_authz import permission_required
from app.db.session import get_db
from app.models.custom_scope import CustomScopeItem, CustomScopeSet
from app.models.site import Site
from app.models.tenant import Tenant, TenantSiteBinding
from app.models.user import User
from app.schemas.custom_scope import CustomScopeSetCreate, CustomScopeSetResponse, CustomScopeSetUpdate
from app.services.access_control import AccessContext
from app.services.operation_log import write_operation_log

router = APIRouter(prefix="/custom-scope-sets", tags=["custom-scope-sets"])


def _assert_tenant_allowed(access: AccessContext, tenant_id: int):
    if access.can_global_read:
        return
    if tenant_id not in access.tenant_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只能管理本公司自定义范围")


def _validate_resource_ids(db: Session, tenant_id: int, resource_type: str, resource_ids: list[int]):
    if resource_type != "site":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前版本只支持站点范围集合")
    if not resource_ids:
        return

    existing = set(db.scalars(select(Site.id).where(Site.id.in_(resource_ids))).all())
    if len(existing) != len(set(resource_ids)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="存在无效站点")

    tenant_site_ids = set(
        db.scalars(
            select(TenantSiteBinding.site_id).where(
                TenantSiteBinding.tenant_id == tenant_id,
                TenantSiteBinding.site_id.in_(resource_ids),
            )
        ).all()
    )
    if len(tenant_site_ids) != len(set(resource_ids)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="存在不属于当前公司的站点")


def _to_response(item: CustomScopeSet, tenant_code: str) -> CustomScopeSetResponse:
    resource_ids = sorted({row.resource_id for row in item.items})
    return CustomScopeSetResponse(
        id=item.id,
        tenant_code=tenant_code,
        name=item.name,
        resource_type=item.resource_type,
        resource_ids=resource_ids,
        item_count=len(resource_ids),
    )


@router.get("", response_model=list[CustomScopeSetResponse])
def list_custom_scope_sets(
    tenant_code: str,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(permission_required("user.manage")),
):
    tenant = db.scalar(select(Tenant).where(Tenant.code == tenant_code))
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="公司不存在")
    _assert_tenant_allowed(access, tenant.id)

    rows = list(
        db.scalars(
            select(CustomScopeSet)
            .where(CustomScopeSet.tenant_id == tenant.id)
            .options(selectinload(CustomScopeSet.items))
            .order_by(CustomScopeSet.id.desc())
        ).all()
    )
    return [_to_response(item, tenant.code) for item in rows]


@router.post("", response_model=CustomScopeSetResponse)
def create_custom_scope_set(
    tenant_code: str,
    payload: CustomScopeSetCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    access: AccessContext = Depends(permission_required("user.manage")),
):
    tenant = db.scalar(select(Tenant).where(Tenant.code == tenant_code))
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="公司不存在")
    _assert_tenant_allowed(access, tenant.id)
    _validate_resource_ids(db, tenant.id, payload.resource_type, payload.resource_ids)

    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="自定义范围名称不能为空")

    item = CustomScopeSet(
        tenant_id=tenant.id,
        name=name,
        resource_type=payload.resource_type,
        created_by=current_user.id,
    )
    db.add(item)
    db.flush()
    for resource_id in sorted(set(payload.resource_ids)):
        db.add(CustomScopeItem(scope_set_id=item.id, resource_id=resource_id))
    write_operation_log(
        db,
        operator_id=current_user.id,
        tenant_id=tenant.id,
        action="custom_scope.create",
        target_type="custom_scope_set",
        target_id=str(item.id),
        content=f"创建自定义范围 {item.name}，资源数={len(set(payload.resource_ids))}",
    )
    db.commit()
    db.refresh(item)
    return _to_response(item, tenant.code)


@router.put("/{scope_set_id}", response_model=CustomScopeSetResponse)
def update_custom_scope_set(
    scope_set_id: int,
    tenant_code: str,
    payload: CustomScopeSetUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    access: AccessContext = Depends(permission_required("user.manage")),
):
    item = db.scalar(
        select(CustomScopeSet)
        .where(CustomScopeSet.id == scope_set_id)
        .options(selectinload(CustomScopeSet.items))
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="自定义范围不存在")

    tenant = db.get(Tenant, item.tenant_id)
    if tenant is None or tenant.code != tenant_code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="公司与自定义范围不匹配")
    _assert_tenant_allowed(access, tenant.id)
    _validate_resource_ids(db, tenant.id, item.resource_type, payload.resource_ids)

    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="自定义范围名称不能为空")
    item.name = name

    for row in list(item.items):
        db.delete(row)
    db.flush()
    for resource_id in sorted(set(payload.resource_ids)):
        db.add(CustomScopeItem(scope_set_id=item.id, resource_id=resource_id))
    write_operation_log(
        db,
        operator_id=current_user.id,
        tenant_id=tenant.id,
        action="custom_scope.update",
        target_type="custom_scope_set",
        target_id=str(item.id),
        content=f"更新自定义范围 {item.name}，资源数={len(set(payload.resource_ids))}",
    )
    db.commit()
    db.refresh(item)
    return _to_response(item, tenant.code)


@router.delete("/{scope_set_id}")
def delete_custom_scope_set(
    scope_set_id: int,
    tenant_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    access: AccessContext = Depends(permission_required("user.manage")),
):
    item = db.get(CustomScopeSet, scope_set_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="自定义范围不存在")
    tenant = db.get(Tenant, item.tenant_id)
    if tenant is None or tenant.code != tenant_code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="公司与自定义范围不匹配")
    _assert_tenant_allowed(access, tenant.id)
    write_operation_log(
        db,
        operator_id=current_user.id,
        tenant_id=tenant.id,
        action="custom_scope.delete",
        target_type="custom_scope_set",
        target_id=str(item.id),
        content=f"删除自定义范围 {item.name}",
    )
    db.delete(item)
    db.commit()
    return {"message": "自定义范围已删除"}
