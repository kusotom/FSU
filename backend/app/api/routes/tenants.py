from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_access_context, get_current_user, require_platform_admin
from app.db.session import get_db
from app.models.tenant import Tenant
from app.schemas.tenant import TenantCreate, TenantResponse
from app.services.access_control import AccessContext

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.get("", response_model=list[TenantResponse])
def list_tenants(
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
    access: AccessContext = Depends(get_access_context),
):
    stmt = select(Tenant).where(Tenant.is_active.is_(True)).order_by(Tenant.id.asc())
    if not access.can_global_read:
        if not access.tenant_ids:
            return []
        stmt = stmt.where(Tenant.id.in_(access.tenant_ids))

    rows = list(db.scalars(stmt).all())
    parent_by_id = {row.id: row.code for row in rows}
    missing_parent_ids = {row.parent_id for row in rows if row.parent_id and row.parent_id not in parent_by_id}
    if missing_parent_ids:
        parent_rows = db.execute(select(Tenant.id, Tenant.code).where(Tenant.id.in_(missing_parent_ids))).all()
        for tenant_id, tenant_code in parent_rows:
            parent_by_id[tenant_id] = tenant_code

    return [
        TenantResponse(
            id=row.id,
            code=row.code,
            name=row.name,
            tenant_type=row.tenant_type,
            parent_code=parent_by_id.get(row.parent_id),
            is_active=row.is_active,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.post("", response_model=TenantResponse)
def create_tenant(
    payload: TenantCreate,
    db: Session = Depends(get_db),
    _=Depends(require_platform_admin),
):
    code = str(payload.code or "").strip().upper()
    name = str(payload.name or "").strip()
    tenant_type = str(payload.tenant_type or "").strip() or "subsidiary"
    if not code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="公司编码不能为空")
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="公司名称不能为空")

    exists = db.scalar(select(Tenant).where(Tenant.code == code))
    if exists is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="公司编码已存在")

    parent_id = None
    if payload.parent_code:
        parent = db.scalar(select(Tenant).where(Tenant.code == payload.parent_code))
        if parent is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上级公司不存在")
        parent_id = parent.id

    tenant = Tenant(
        code=code,
        name=name,
        tenant_type=tenant_type,
        parent_id=parent_id,
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    parent_code = None
    if tenant.parent_id:
        parent_code = db.scalar(select(Tenant.code).where(Tenant.id == tenant.parent_id))
    return TenantResponse(
        id=tenant.id,
        code=tenant.code,
        name=tenant.name,
        tenant_type=tenant.tenant_type,
        parent_code=parent_code,
        is_active=tenant.is_active,
        created_at=tenant.created_at,
    )
