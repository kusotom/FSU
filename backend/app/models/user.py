from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Table, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

user_roles = Table(
    "sys_user_role",
    Base.metadata,
    Column("user_id", ForeignKey("sys_user.id"), primary_key=True),
    Column("role_id", ForeignKey("sys_role.id"), primary_key=True),
)


class User(Base):
    __tablename__ = "sys_user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    phone_country_code: Mapped[str] = mapped_column(String(8), nullable=False, default="+86")
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    phone_login_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    login_fail_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    roles: Mapped[list["Role"]] = relationship(
        "Role", secondary=user_roles, back_populates="users", lazy="selectin"
    )
    tenant_roles: Mapped[list["UserTenantRole"]] = relationship(
        "UserTenantRole",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    data_scopes: Mapped[list["UserDataScope"]] = relationship(
        "UserDataScope",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class Role(Base):
    __tablename__ = "sys_role"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    users: Mapped[list[User]] = relationship(
        "User", secondary=user_roles, back_populates="roles", lazy="selectin"
    )
    tenant_roles: Mapped[list["UserTenantRole"]] = relationship(
        "UserTenantRole",
        back_populates="role",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    permissions: Mapped[list["RolePermission"]] = relationship(
        "RolePermission",
        back_populates="role",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class RolePermission(Base):
    __tablename__ = "sys_role_permission"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_key", name="uq_role_permission_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("sys_role.id"), nullable=False, index=True)
    permission_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    role: Mapped[Role] = relationship("Role", back_populates="permissions", lazy="joined")


class UserDataScope(Base):
    __tablename__ = "sys_user_data_scope"
    __table_args__ = (
        UniqueConstraint("user_id", "scope_type", "scope_value", name="uq_user_data_scope"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("sys_user.id"), nullable=False, index=True)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    scope_value: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    scope_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    user: Mapped[User] = relationship("User", back_populates="data_scopes", lazy="joined")
