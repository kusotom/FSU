from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class NotifyReceiver(Base):
    __tablename__ = "notify_receiver"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("sys_user.id"), nullable=True, index=True)
    receiver_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    mobile: Mapped[str | None] = mapped_column(String(32), nullable=True)
    wechat_openid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    email: Mapped[str | None] = mapped_column(String(128), nullable=True)
    pushplus_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("sys_user.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class NotifyGroup(Base):
    __tablename__ = "notify_group"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_notify_group_tenant_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("sys_user.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    members: Mapped[list["NotifyGroupMember"]] = relationship(
        "NotifyGroupMember",
        back_populates="group",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class NotifyGroupMember(Base):
    __tablename__ = "notify_group_member"
    __table_args__ = (
        UniqueConstraint("notify_group_id", "receiver_id", name="uq_notify_group_member"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    notify_group_id: Mapped[int] = mapped_column(
        ForeignKey("notify_group.id", ondelete="CASCADE"), nullable=False, index=True
    )
    receiver_id: Mapped[int] = mapped_column(
        ForeignKey("notify_receiver.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    group: Mapped[NotifyGroup] = relationship("NotifyGroup", back_populates="members", lazy="joined")
    receiver: Mapped[NotifyReceiver] = relationship("NotifyReceiver", lazy="joined")


class NotifyRule(Base):
    __tablename__ = "notify_rule"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False, default="TENANT")
    project_id: Mapped[int | None] = mapped_column(ForeignKey("project.id"), nullable=True, index=True)
    site_id: Mapped[int | None] = mapped_column(ForeignKey("site.id"), nullable=True, index=True)
    device_group_id: Mapped[int | None] = mapped_column(ForeignKey("device_group.id"), nullable=True, index=True)
    custom_scope_set_id: Mapped[int | None] = mapped_column(ForeignKey("custom_scope_set.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    alarm_level_min: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    event_types: Mapped[str] = mapped_column(String(64), nullable=False, default="trigger,recover")
    channel_types: Mapped[str] = mapped_column(String(128), nullable=False, default="wechat,pushplus")
    notify_group_id: Mapped[int | None] = mapped_column(ForeignKey("notify_group.id"), nullable=True, index=True)
    content_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("sys_user.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    notify_group: Mapped[NotifyGroup | None] = relationship("NotifyGroup", lazy="joined")


class OncallSchedule(Base):
    __tablename__ = "oncall_schedule"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_oncall_schedule_tenant_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False, default="TENANT")
    project_id: Mapped[int | None] = mapped_column(ForeignKey("project.id"), nullable=True, index=True)
    site_id: Mapped[int | None] = mapped_column(ForeignKey("site.id"), nullable=True, index=True)
    device_group_id: Mapped[int | None] = mapped_column(ForeignKey("device_group.id"), nullable=True, index=True)
    custom_scope_set_id: Mapped[int | None] = mapped_column(ForeignKey("custom_scope_set.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    timezone_name: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Shanghai")
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("sys_user.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    members: Mapped[list["OncallScheduleMember"]] = relationship(
        "OncallScheduleMember",
        back_populates="schedule",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class OncallScheduleMember(Base):
    __tablename__ = "oncall_schedule_member"
    __table_args__ = (
        UniqueConstraint("schedule_id", "receiver_id", name="uq_oncall_schedule_member"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    schedule_id: Mapped[int] = mapped_column(
        ForeignKey("oncall_schedule.id", ondelete="CASCADE"), nullable=False, index=True
    )
    receiver_id: Mapped[int] = mapped_column(ForeignKey("notify_receiver.id"), nullable=False, index=True)
    duty_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    shift_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    schedule: Mapped[OncallSchedule] = relationship("OncallSchedule", back_populates="members", lazy="joined")
    receiver: Mapped[NotifyReceiver] = relationship("NotifyReceiver", lazy="joined")


class AlarmPushLog(Base):
    __tablename__ = "alarm_push_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("project.id"), nullable=True, index=True)
    site_id: Mapped[int | None] = mapped_column(ForeignKey("site.id"), nullable=True, index=True)
    device_group_id: Mapped[int | None] = mapped_column(ForeignKey("device_group.id"), nullable=True, index=True)
    alarm_id: Mapped[int | None] = mapped_column(ForeignKey("alarm_event.id"), nullable=True, index=True)
    policy_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    channel_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    channel_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    target: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    push_status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    error_message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pushed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )
