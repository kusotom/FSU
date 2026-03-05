from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_access_context, get_current_user
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
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
    access: AccessContext = Depends(get_access_context),
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
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="\u79df\u6237\u4e0d\u5b58\u5728")
    else:
        tenant = None

    if access.can_global_read:
        if tenant is None:
            tenant = get_default_sub_tenant(db)
        return tenant

    if not access.tenant_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="\u65e0\u53ef\u7528\u79df\u6237\u8303\u56f4")

    if tenant is None:
        if len(access.tenant_ids) == 1:
            tenant = db.get(Tenant, next(iter(access.tenant_ids)))
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="\u8bf7\u6307\u5b9a\u79df\u6237")
    if tenant is None or tenant.id not in access.tenant_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="\u65e0\u6743\u5728\u8be5\u79df\u6237\u521b\u5efa\u7ad9\u70b9")
    return tenant


@router.post("", response_model=SiteResponse)
def create_site(
    payload: SiteCreate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
    access: AccessContext = Depends(get_access_context),
):
    if not access.can_manage_tenant_assets:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="\u65e0\u6743\u521b\u5efa\u7ad9\u70b9")

    exists = db.scalar(select(Site).where(Site.code == payload.code))
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="\u7ad9\u70b9\u7f16\u7801\u5df2\u5b58\u5728")

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
    _=Depends(get_current_user),
    access: AccessContext = Depends(get_access_context),
):
    if not access.can_manage_tenant_assets:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="\u65e0\u6743\u7f16\u8f91\u7ad9\u70b9")

    site = db.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="\u7ad9\u70b9\u4e0d\u5b58\u5728")

    scoped_ids = get_accessible_site_ids(db, access)
    if scoped_ids is not None and site_id not in scoped_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="\u65e0\u6743\u7f16\u8f91\u8be5\u7ad9\u70b9")

    payload_fields = payload.model_fields_set

    if "code" in payload_fields:
        next_code = (payload.code or "").strip()
        if not next_code:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="\u7ad9\u70b9\u7f16\u7801\u4e0d\u80fd\u4e3a\u7a7a")
        exists = db.scalar(select(Site).where(Site.code == next_code, Site.id != site_id))
        if exists:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="\u7ad9\u70b9\u7f16\u7801\u5df2\u5b58\u5728")
        site.code = next_code

    if "name" in payload_fields:
        next_name = (payload.name or "").strip()
        if not next_name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="\u7ad9\u70b9\u540d\u79f0\u4e0d\u80fd\u4e3a\u7a7a")
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
