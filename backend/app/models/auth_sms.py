from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SmsCodeLog(Base):
    __tablename__ = "sms_code_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    scene: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    phone_country_code: Mapped[str] = mapped_column(String(8), nullable=False, default="+86")
    phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("sys_user.id"), nullable=True, index=True)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenant.id"), nullable=True, index=True)
    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    send_status: Mapped[str] = mapped_column(String(16), nullable=False, default="SUCCESS")
    verify_status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client_device_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sms_vendor: Mapped[str | None] = mapped_column(String(32), nullable=True)
    vendor_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user = relationship("User", lazy="joined")


class AuthSmsCode(Base):
    __tablename__ = "auth_sms_code"
    __table_args__ = (
        UniqueConstraint("request_id", name="uk_auth_sms_code_request_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    scene: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("sys_user.id"), nullable=True, index=True)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenant.id"), nullable=True, index=True)
    phone_country_code: Mapped[str] = mapped_column(String(8), nullable=False, default="+86")
    phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    phone_e164: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    code_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    code_salt: Mapped[str] = mapped_column(String(64), nullable=False)
    code_length: Mapped[int] = mapped_column(Integer, nullable=False, default=6)
    send_status: Mapped[str] = mapped_column(String(16), nullable=False, default="INIT", index=True)
    verify_status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING", index=True)
    verify_fail_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_verify_fail_count: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    client_ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    client_user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_device_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="unisms")
    provider_template_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_signature: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)

    user = relationship("User", lazy="joined")
    deliveries: Mapped[list["AuthSmsDeliveryLog"]] = relationship(
        "AuthSmsDeliveryLog",
        back_populates="sms_code",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class AuthSmsDeliveryLog(Base):
    __tablename__ = "auth_sms_delivery_log"
    __table_args__ = (
        UniqueConstraint("provider", "provider_message_id", name="uk_auth_sms_delivery_provider_msg"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    sms_code_id: Mapped[int | None] = mapped_column(ForeignKey("auth_sms_code.id"), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="unisms")
    provider_message_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider_action: Mapped[str] = mapped_column(String(64), nullable=False, default="sms.message.send")
    phone_e164: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    submit_http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    submit_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    submit_message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    submit_status: Mapped[str] = mapped_column(String(16), nullable=False, default="INIT", index=True)
    upstream: Mapped[str | None] = mapped_column(String(64), nullable=True)
    message_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    submit_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    submit_response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    dlr_status: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    dlr_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dlr_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    submit_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    done_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_webhook_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    raw_webhook_headers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    webhook_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    webhook_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)

    sms_code: Mapped[AuthSmsCode | None] = relationship("AuthSmsCode", back_populates="deliveries", lazy="joined")
