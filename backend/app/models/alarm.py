from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AlarmEvent(Base):
    __tablename__ = "alarm_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("site.id"), index=True, nullable=False)
    device_id: Mapped[int] = mapped_column(ForeignKey("fsu_device.id"), index=True, nullable=False)
    point_id: Mapped[int] = mapped_column(ForeignKey("monitor_point.id"), index=True, nullable=False)
    alarm_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    alarm_name: Mapped[str] = mapped_column(String(128), nullable=False)
    alarm_level: Mapped[int] = mapped_column(default=2, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False, index=True)
    trigger_value: Mapped[float] = mapped_column(nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[int | None] = mapped_column(ForeignKey("sys_user.id"), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by: Mapped[int | None] = mapped_column(ForeignKey("sys_user.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class AlarmActionLog(Base):
    __tablename__ = "alarm_action_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alarm_id: Mapped[int] = mapped_column(ForeignKey("alarm_event.id"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("sys_user.id"), nullable=True)
    content: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class AlarmConditionState(Base):
    __tablename__ = "alarm_condition_state"
    __table_args__ = (UniqueConstraint("point_id", "rule_id", name="uq_alarm_condition_point_rule"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    point_id: Mapped[int] = mapped_column(ForeignKey("monitor_point.id"), nullable=False, index=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("alarm_rule.id"), nullable=False, index=True)
    abnormal_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    normal_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
