from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class BInterfaceHistory(Base):
    __tablename__ = "b_interface_history"
    __table_args__ = (
        UniqueConstraint("fsu_id", "device_id", "semaphore_id", "sample_time", name="uq_bif_history_point"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    fsu_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    fsu_code: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    device_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    device_code: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    device_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    semaphore_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    semaphore_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    measured_val: Mapped[str | None] = mapped_column(String(128), nullable=True)
    setup_val: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sample_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    mapping_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    standard_signal_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    mapped_ids: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    base_type_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    local_signal_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    signal_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    signal_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    signal_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    channel_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    signal_meanings: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    raw_fragment: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    source_call_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False, index=True)
