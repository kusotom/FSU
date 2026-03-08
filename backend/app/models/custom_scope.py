from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CustomScopeSet(Base):
    __tablename__ = "custom_scope_set"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_custom_scope_set_tenant_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False, default="site")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("sys_user.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    tenant = relationship("Tenant", lazy="joined")
    items = relationship(
        "CustomScopeItem",
        back_populates="scope_set",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class CustomScopeItem(Base):
    __tablename__ = "custom_scope_item"
    __table_args__ = (
        UniqueConstraint("scope_set_id", "resource_id", name="uq_custom_scope_item"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    scope_set_id: Mapped[int] = mapped_column(
        ForeignKey("custom_scope_set.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resource_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    scope_set = relationship("CustomScopeSet", back_populates="items", lazy="joined")
