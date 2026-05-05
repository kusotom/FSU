from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, JSON, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


SQLITE_SAFE_JSONB = JSONB().with_variant(JSON(), "sqlite")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class BInterfaceFsuInfoCache(Base):
    __tablename__ = "b_interface_fsuinfo_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    fsu_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    fsu_code: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    cpu_usage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mem_usage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result: Mapped[str | None] = mapped_column(String(32), nullable=True)
    raw_xml_sanitized: Mapped[str] = mapped_column(String(4000), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)


class BInterfaceLoginInfoCache(Base):
    __tablename__ = "b_interface_logininfo_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    fsu_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    fsu_code: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    sc_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fsu_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ipsec_ip: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ipsec_user: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ftp_user: Mapped[str | None] = mapped_column(String(128), nullable=True)
    device_list: Mapped[list[str] | None] = mapped_column(SQLITE_SAFE_JSONB, nullable=True)
    result: Mapped[str | None] = mapped_column(String(32), nullable=True)
    raw_xml_sanitized: Mapped[str] = mapped_column(String(4000), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)
