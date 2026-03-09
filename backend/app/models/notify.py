from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NotifyChannel(Base):
    __tablename__ = "notify_channel"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    channel_type: Mapped[str] = mapped_column(String(32), nullable=False, default="webhook")
    endpoint: Mapped[str] = mapped_column(String(512), nullable=False)
    secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class NotifyPolicy(Base):
    __tablename__ = "notify_policy"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    channel_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("notify_channel.id"), nullable=False, index=True
    )
    channel_ids: Mapped[str | None] = mapped_column(String(255), nullable=True)
    min_alarm_level: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    event_types: Mapped[str] = mapped_column(String(64), nullable=False, default="trigger,recover")
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
