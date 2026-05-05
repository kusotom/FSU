from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class BInterfaceCurrentAlarm(Base):
    __tablename__ = "b_interface_current_alarm"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    fsu_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    fsu_code: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    serial_no: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    alarm_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    device_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    device_code: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    alarm_time: Mapped[str | None] = mapped_column(String(64), nullable=True)
    alarm_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    alarm_flag: Mapped[str | None] = mapped_column(String(32), nullable=True)
    alarm_desc: Mapped[str | None] = mapped_column(String(512), nullable=True)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)


class BInterfaceAlarmHistory(Base):
    __tablename__ = "b_interface_alarm_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    fsu_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    fsu_code: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    serial_no: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    alarm_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    device_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    device_code: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    alarm_time: Mapped[str | None] = mapped_column(String(64), nullable=True)
    alarm_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    alarm_flag: Mapped[str | None] = mapped_column(String(32), nullable=True)
    alarm_desc: Mapped[str | None] = mapped_column(String(512), nullable=True)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    begin_time: Mapped[str | None] = mapped_column(String(64), nullable=True)
    end_time: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)
