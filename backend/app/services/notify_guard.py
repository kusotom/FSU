from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.custom_scope import CustomScopeSet
from app.models.device_group import DeviceGroup
from app.models.project import Project
from app.models.site import Site
from app.models.tenant import Tenant, TenantSiteBinding
from app.services.access_control import AccessContext, find_tenant_by_code, get_accessible_site_ids


def get_tenant_by_code_or_404(db: Session, tenant_code: str) -> Tenant:
    tenant = find_tenant_by_code(db, tenant_code)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="公司不存在")
    return tenant


def ensure_tenant_allowed(access: AccessContext, tenant_id: int) -> None:
    if access.can_global_read:
        return
    if tenant_id not in access.tenant_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只能管理本公司数据")


def ensure_scope_allowed(
    db: Session,
    access: AccessContext,
    *,
    tenant_id: int,
    project_id: int | None = None,
    site_id: int | None = None,
    device_group_id: int | None = None,
    custom_scope_set_id: int | None = None,
) -> None:
    ensure_tenant_allowed(access, tenant_id)
    if access.can_global_read:
        return

    if project_id and access.project_ids and project_id not in access.project_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="超出项目范围")

    if site_id:
        if access.site_ids and site_id not in access.site_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="超出站点范围")
        accessible_site_ids = get_accessible_site_ids(db, access)
        if accessible_site_ids is not None and site_id not in accessible_site_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="超出站点范围")

    if device_group_id and access.device_group_ids and device_group_id not in access.device_group_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="超出设备组范围")

    if custom_scope_set_id and access.custom_scope_set_ids and custom_scope_set_id not in access.custom_scope_set_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="超出自定义范围")


def validate_project_belongs_tenant(db: Session, tenant_id: int, project_id: int) -> None:
    exists = db.scalar(select(Project.id).where(Project.id == project_id, Project.tenant_id == tenant_id))
    if exists is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="项目不属于当前公司")


def validate_site_belongs_tenant(db: Session, tenant_id: int, site_id: int) -> None:
    site = db.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="站点不存在")
    binding = db.scalar(
        select(TenantSiteBinding.id).where(
            TenantSiteBinding.tenant_id == tenant_id,
            TenantSiteBinding.site_id == site_id,
        )
    )
    if binding is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="站点不属于当前公司")


def validate_device_group_belongs_tenant(db: Session, tenant_id: int, device_group_id: int) -> None:
    exists = db.scalar(
        select(DeviceGroup.id).where(
            DeviceGroup.id == device_group_id,
            DeviceGroup.tenant_id == tenant_id,
        )
    )
    if exists is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="设备组不属于当前公司")


def validate_custom_scope_belongs_tenant(db: Session, tenant_id: int, custom_scope_set_id: int) -> None:
    exists = db.scalar(
        select(CustomScopeSet.id).where(
            CustomScopeSet.id == custom_scope_set_id,
            CustomScopeSet.tenant_id == tenant_id,
        )
    )
    if exists is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="自定义范围不属于当前公司")
