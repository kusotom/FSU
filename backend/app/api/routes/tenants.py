from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_access_context, get_current_user
from app.db.session import get_db
from app.models.tenant import Tenant
from app.schemas.tenant import TenantResponse
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
        parent_rows = db.execute(
            select(Tenant.id, Tenant.code).where(Tenant.id.in_(missing_parent_ids))
        ).all()
        for tenant_id, tenant_code in parent_rows:
            parent_by_id[tenant_id] = tenant_code
    result = []
    for row in rows:
        result.append(
            TenantResponse(
                id=row.id,
                code=row.code,
                name=row.name,
                tenant_type=row.tenant_type,
                parent_code=parent_by_id.get(row.parent_id),
                is_active=row.is_active,
                created_at=row.created_at,
            )
        )
    return result
