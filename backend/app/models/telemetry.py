from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TelemetryLatest(Base):
    __tablename__ = "telemetry_latest"
    __table_args__ = (
        UniqueConstraint("point_id", name="uq_latest_point"),
        Index("ix_telemetry_latest_collected_at", "collected_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    point_id: Mapped[int] = mapped_column(ForeignKey("monitor_point.id"), nullable=False, index=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    point: Mapped["MonitorPoint"] = relationship("MonitorPoint", back_populates="latest", lazy="joined")


class TelemetryHistory(Base):
    __tablename__ = "telemetry_history"
    __table_args__ = (
        Index("ix_telemetry_history_point_collected_at", "point_id", "collected_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    point_id: Mapped[int] = mapped_column(ForeignKey("monitor_point.id"), nullable=False, index=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
