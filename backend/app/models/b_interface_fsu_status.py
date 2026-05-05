from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, JSON, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


SQLITE_SAFE_JSONB = JSONB().with_variant(JSON(), "sqlite")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class BInterfaceFsuStatus(Base):
    __tablename__ = "b_interface_fsu_status"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    fsu_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    fsu_code: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    fsu_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mac_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reg_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fsu_vendor: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fsu_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fsu_class: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    dict_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    device_list: Mapped[list[str] | None] = mapped_column(SQLITE_SAFE_JSONB, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    remote_addr: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)
