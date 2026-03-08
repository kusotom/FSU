from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_access_context
from app.api.deps_authz import permission_required
from app.db.session import get_db
from app.models.site import Site
from app.models.tenant import Tenant, TenantSiteBinding
from app.schemas.site import SiteCreate, SiteResponse, SiteUpdate
from app.services.access_control import (
    AccessContext,
    ensure_site_tenant_binding,
    get_accessible_site_ids,
    get_default_sub_tenant,
)

router = APIRouter(prefix="/sites", tags=["sites"])


@router.get("")
def list_sites(
    tenant_code: str | None = None,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(permission_required("site.view")),
):
    site_ids = get_accessible_site_ids(db, access)
    if site_ids is not None and not site_ids:
        return []

    stmt = (
        select(
            Site.id,
            Site.code,
            Site.name,
            Site.region,
            Site.is_active,
            Site.created_at,
            Tenant.code.label("tenant_code"),
        )
        .outerjoin(TenantSiteBinding, TenantSiteBinding.site_id == Site.id)
        .outerjoin(Tenant, Tenant.id == TenantSiteBinding.tenant_id)
        .order_by(Site.id.desc())
    )
    if tenant_code:
        stmt = stmt.where(Tenant.code == tenant_code)
    if site_ids is not None:
        stmt = stmt.where(Site.id.in_(site_ids))
    rows = db.execute(stmt).all()

    data = []
    for row in rows:
        created_at = row.created_at.isoformat() if row.created_at else None
        data.append(
            {
                "id": row.id,
                "code": row.code,
                "name": row.name,
                "region": row.region,
                "tenant_code": row.tenant_code,
                "is_active": row.is_active,
                "created_at": created_at,
            }
        )
    return data


def _resolve_create_target_tenant(
    db: Session,
    access: AccessContext,
    tenant_code: str | None,
) -> Tenant:
    if tenant_code:
        tenant = db.scalar(select(Tenant).where(Tenant.code == tenant_code))
        if tenant is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="租户不存在")
    else:
        tenant = None

    if access.can_global_read:
        if tenant is None:
            tenant = get_default_sub_tenant(db)
        return tenant

    if not access.tenant_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无可用租户范围")

    if tenant is None:
        if len(access.tenant_ids) == 1:
            tenant = db.get(Tenant, next(iter(access.tenant_ids)))
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请指定租户")
    if tenant is None or tenant.id not in access.tenant_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权在该租户创建站点")
    return tenant


@router.post("", response_model=SiteResponse)
def create_site(
    payload: SiteCreate,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(permission_required("site.create")),
):
    exists = db.scalar(select(Site).where(Site.code == payload.code))
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="站点编码已存在")

    tenant = _resolve_create_target_tenant(db, access, payload.tenant_code)
    site = Site(
        code=payload.code,
        name=payload.name,
        region=payload.region,
        created_at=datetime.now(timezone.utc),
    )
    db.add(site)
    db.flush()
    ensure_site_tenant_binding(db, site_id=site.id, tenant_id=tenant.id)
    db.commit()
    db.refresh(site)
    return SiteResponse(
        id=site.id,
        code=site.code,
        name=site.name,
        region=site.region,
        tenant_code=tenant.code,
        is_active=site.is_active,
        created_at=site.created_at,
    )


@router.put("/{site_id}", response_model=SiteResponse)
def update_site(
    site_id: int,
    payload: SiteUpdate,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(permission_required("site.update")),
):
    site = db.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="站点不存在")

    scoped_ids = get_accessible_site_ids(db, access)
    if scoped_ids is not None and site_id not in scoped_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权编辑该站点")

    payload_fields = payload.model_fields_set

    if "code" in payload_fields:
        next_code = (payload.code or "").strip()
        if not next_code:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="站点编码不能为空")
        exists = db.scalar(select(Site).where(Site.code == next_code, Site.id != site_id))
        if exists:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="站点编码已存在")
        site.code = next_code

    if "name" in payload_fields:
        next_name = (payload.name or "").strip()
        if not next_name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="站点名称不能为空")
        site.name = next_name

    if "region" in payload_fields:
        site.region = (payload.region or "").strip() or None

    if "is_active" in payload_fields and payload.is_active is not None:
        site.is_active = payload.is_active

    current_binding = db.scalar(select(TenantSiteBinding).where(TenantSiteBinding.site_id == site.id))
    if "tenant_code" in payload_fields:
        tenant = _resolve_create_target_tenant(db, access, payload.tenant_code)
        ensure_site_tenant_binding(db, site_id=site.id, tenant_id=tenant.id)
    elif current_binding is None:
        tenant = _resolve_create_target_tenant(db, access, None)
        ensure_site_tenant_binding(db, site_id=site.id, tenant_id=tenant.id)

    db.commit()
    db.refresh(site)

    tenant_row = db.execute(
        select(Tenant.code)
        .select_from(TenantSiteBinding)
        .join(Tenant, Tenant.id == TenantSiteBinding.tenant_id)
        .where(TenantSiteBinding.site_id == site.id)
    ).first()
    tenant_code = tenant_row[0] if tenant_row else None
    return SiteResponse(
        id=site.id,
        code=site.code,
        name=site.name,
        region=site.region,
        tenant_code=tenant_code,
        is_active=site.is_active,
        created_at=site.created_at,
    )
