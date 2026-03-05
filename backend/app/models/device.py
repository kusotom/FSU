from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class FSUDevice(Base):
    __tablename__ = "fsu_device"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("site.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    vendor: Mapped[str] = mapped_column(String(64), default="Vertiv e-stone", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="online", nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    site: Mapped["Site"] = relationship("Site", back_populates="devices", lazy="joined")
    monitor_points: Mapped[list["MonitorPoint"]] = relationship(
        "MonitorPoint", back_populates="device", cascade="all, delete-orphan", lazy="selectin"
    )


class MonitorPoint(Base):
    __tablename__ = "monitor_point"
    __table_args__ = (UniqueConstraint("device_id", "point_key", name="uq_monitor_point_device_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("fsu_device.id"), nullable=False, index=True)
    point_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    point_name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(32), default="power", nullable=False)
    unit: Mapped[str | None] = mapped_column(String(16), nullable=True)
    high_threshold: Mapped[float | None] = mapped_column(nullable=True)
    low_threshold: Mapped[float | None] = mapped_column(nullable=True)

    device: Mapped[FSUDevice] = relationship("FSUDevice", back_populates="monitor_points", lazy="joined")
    latest: Mapped["TelemetryLatest | None"] = relationship(
        "TelemetryLatest", back_populates="point", uselist=False, cascade="all, delete-orphan", lazy="selectin"
    )
