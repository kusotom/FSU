from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Tenant(Base):
    __tablename__ = "tenant"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    tenant_type: Mapped[str] = mapped_column(String(32), nullable=False, default="subsidiary")
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("tenant.id"), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    parent: Mapped["Tenant | None"] = relationship("Tenant", remote_side=[id], lazy="joined")


class TenantSiteBinding(Base):
    __tablename__ = "tenant_site_binding"
    __table_args__ = (
        UniqueConstraint("site_id", name="uq_tenant_site_binding_site"),
        UniqueConstraint("tenant_id", "site_id", name="uq_tenant_site_binding_tenant_site"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("site.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    tenant: Mapped["Tenant"] = relationship("Tenant", lazy="joined")


class UserTenantRole(Base):
    __tablename__ = "user_tenant_role"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", "tenant_id", name="uq_user_tenant_role"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("sys_user.id"), nullable=False, index=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("sys_role.id"), nullable=False, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    scope_level: Mapped[str] = mapped_column(String(32), nullable=False, default="tenant")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    user: Mapped["User"] = relationship("User", back_populates="tenant_roles", lazy="joined")
    role: Mapped["Role"] = relationship("Role", back_populates="tenant_roles", lazy="joined")
    tenant: Mapped["Tenant"] = relationship("Tenant", lazy="joined")
