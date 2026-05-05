from __future__ import annotations

from datetime import datetime, timezone
import uuid

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _call_id() -> str:
    return uuid.uuid4().hex


class BInterfaceOutboundCall(Base):
    __tablename__ = "b_interface_outbound_call"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    call_id: Mapped[str] = mapped_column(String(32), unique=True, index=True, default=_call_id, nullable=False)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    action: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    fsu_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    fsu_code: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    endpoint: Mapped[str | None] = mapped_column(String(512), nullable=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    request_xml_sanitized: Mapped[str] = mapped_column(String(4000), nullable=False)
    soap_request_sanitized: Mapped[str] = mapped_column(String(4000), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_text_sanitized: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    invoke_return_sanitized: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    business_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    business_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    elapsed_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False, index=True)
