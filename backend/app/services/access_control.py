from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.site import Site
from app.models.tenant import Tenant, TenantSiteBinding, UserTenantRole
from app.models.user import User
from app.schemas.tenant import UserTenantRoleView

HQ_TENANT_CODE = "HQ-GROUP"
DEFAULT_SUB_TENANT_CODE = "SUB-A"


@dataclass
class AccessContext:
    user_id: int
    role_names: set[str]
    tenant_ids: set[int]
    tenant_codes: set[str]
    tenant_roles: list[UserTenantRoleView]
    is_admin: bool
    is_hq_noc: bool
    is_sub_noc: bool

    @property
    def can_global_read(self) -> bool:
        return self.is_admin or self.is_hq_noc

    @property
    def can_manage_templates(self) -> bool:
        return self.is_admin or self.is_hq_noc

    @property
    def can_view_tenant_strategy(self) -> bool:
        return self.is_admin or self.is_hq_noc or self.is_sub_noc

    @property
    def can_edit_tenant_strategy(self) -> bool:
        return self.is_admin or self.is_sub_noc

    @property
    def can_manage_tenant_assets(self) -> bool:
        return self.is_admin or self.is_sub_noc


def build_access_context(db: Session, user: User) -> AccessContext:
    role_names = {item.name for item in user.roles}
    tenant_ids: set[int] = set()
    tenant_codes: set[str] = set()
    tenant_roles: list[UserTenantRoleView] = []
    is_hq_noc = False

    rows = list(
        db.execute(
            select(UserTenantRole)
            .where(UserTenantRole.user_id == user.id)
            .order_by(UserTenantRole.id.asc())
        ).scalars()
    )
    for row in rows:
        role_name = row.role.name
        tenant_code = row.tenant.code
        role_names.add(role_name)
        tenant_ids.add(row.tenant_id)
        tenant_codes.add(tenant_code)
        tenant_roles.append(
            UserTenantRoleView(
                tenant_code=tenant_code,
                tenant_name=row.tenant.name,
                tenant_type=row.tenant.tenant_type,
                role_name=role_name,
                scope_level=row.scope_level,
            )
        )
        if role_name == "hq_noc" and tenant_code == HQ_TENANT_CODE:
            is_hq_noc = True

    return AccessContext(
        user_id=user.id,
        role_names=role_names,
        tenant_ids=tenant_ids,
        tenant_codes=tenant_codes,
        tenant_roles=tenant_roles,
        is_admin=("admin" in role_names),
        is_hq_noc=is_hq_noc,
        is_sub_noc=("sub_noc" in role_names),
    )


def get_accessible_site_ids(db: Session, access: AccessContext) -> set[int] | None:
    if access.can_global_read:
        return None
    if not access.tenant_ids:
        return set()
    return set(
        db.scalars(
            select(TenantSiteBinding.site_id).where(TenantSiteBinding.tenant_id.in_(access.tenant_ids))
        ).all()
    )


def find_tenant_by_code(db: Session, tenant_code: str) -> Tenant | None:
    code = tenant_code.strip()
    if not code:
        return None
    return db.scalar(select(Tenant).where(Tenant.code == code))


def ensure_site_tenant_binding(db: Session, *, site_id: int, tenant_id: int):
    exists = db.scalar(
        select(TenantSiteBinding).where(TenantSiteBinding.site_id == site_id)
    )
    if exists is not None:
        if exists.tenant_id != tenant_id:
            exists.tenant_id = tenant_id
        return
    db.add(
        TenantSiteBinding(
            tenant_id=tenant_id,
            site_id=site_id,
            created_at=datetime.now(timezone.utc),
        )
    )


def get_default_sub_tenant(db: Session) -> Tenant:
    tenant = db.scalar(select(Tenant).where(Tenant.code == DEFAULT_SUB_TENANT_CODE))
    if tenant:
        return tenant
    tenant = db.scalar(select(Tenant).where(Tenant.code == HQ_TENANT_CODE))
    if tenant:
        return tenant
    tenant = db.scalar(select(Tenant).order_by(Tenant.id.asc()))
    if tenant:
        return tenant
    raise ValueError("未找到可用租户")


def get_site_tenant_code_map(db: Session, site_ids: list[int]) -> dict[int, str]:
    if not site_ids:
        return {}
    rows = db.execute(
        select(TenantSiteBinding.site_id, Tenant.code)
        .join(Tenant, Tenant.id == TenantSiteBinding.tenant_id)
        .where(TenantSiteBinding.site_id.in_(site_ids))
    ).all()
    return {site_id: tenant_code for site_id, tenant_code in rows}


def get_tenant_for_site(db: Session, site_id: int) -> Tenant | None:
    binding = db.scalar(select(TenantSiteBinding).where(TenantSiteBinding.site_id == site_id))
    if binding is None:
        return None
    return db.get(Tenant, binding.tenant_id)


def get_tenant_for_site_code(db: Session, site_code: str) -> Tenant | None:
    site = db.scalar(select(Site).where(Site.code == site_code))
    if site is None:
        return None
    return get_tenant_for_site(db, site.id)

