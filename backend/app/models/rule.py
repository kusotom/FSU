from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AlarmRule(Base):
    __tablename__ = "alarm_rule"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    rule_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    rule_name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="power")
    metric_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    alarm_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    comparison: Mapped[str] = mapped_column(String(24), nullable=False, default="gt")
    threshold_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    alarm_level: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class AlarmRuleTenantPolicy(Base):
    __tablename__ = "alarm_rule_tenant_policy"
    __table_args__ = (
        UniqueConstraint("template_rule_id", "tenant_id", name="uq_alarm_rule_tenant_policy"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    template_rule_id: Mapped[int] = mapped_column(
        ForeignKey("alarm_rule.id"), nullable=False, index=True
    )
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    is_enabled_override: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    threshold_value_override: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_seconds_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    alarm_level_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    template_rule: Mapped["AlarmRule"] = relationship("AlarmRule", lazy="joined")
    tenant: Mapped["Tenant"] = relationship("Tenant", lazy="joined")
