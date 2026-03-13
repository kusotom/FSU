"""sms auth fields and logs

Revision ID: 20260312_0008
Revises: 20260306_0007
Create Date: 2026-03-12 11:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260312_0008"
down_revision: Union[str, None] = "20260306_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sys_user", sa.Column("phone_country_code", sa.String(length=8), nullable=True))
    op.add_column("sys_user", sa.Column("phone", sa.String(length=20), nullable=True))
    op.add_column("sys_user", sa.Column("status", sa.String(length=16), nullable=True))
    op.add_column("sys_user", sa.Column("phone_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sys_user", sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sys_user", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sys_user", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sys_user", sa.Column("login_fail_count", sa.Integer(), nullable=True))

    op.execute("UPDATE sys_user SET phone_country_code = '+86' WHERE phone_country_code IS NULL")
    op.execute("UPDATE sys_user SET status = 'ACTIVE' WHERE status IS NULL")
    op.execute("UPDATE sys_user SET login_fail_count = 0 WHERE login_fail_count IS NULL")

    with op.batch_alter_table("sys_user") as batch_op:
        batch_op.alter_column("phone_country_code", existing_type=sa.String(length=8), nullable=False)
        batch_op.alter_column("status", existing_type=sa.String(length=16), nullable=False)
        batch_op.alter_column("login_fail_count", existing_type=sa.Integer(), nullable=False)

    op.create_index("ix_sys_user_phone", "sys_user", ["phone"], unique=False)
    op.create_index("ix_sys_user_status", "sys_user", ["status"], unique=False)
    op.create_index(
        "uk_sys_user_phone_country_phone",
        "sys_user",
        ["phone_country_code", "phone"],
        unique=True,
    )

    op.create_table(
        "sms_code_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("scene", sa.String(length=16), nullable=False),
        sa.Column("phone_country_code", sa.String(length=8), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("tenant_id", sa.Integer(), nullable=True),
        sa.Column("code_hash", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("send_status", sa.String(length=16), nullable=False),
        sa.Column("verify_status", sa.String(length=16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("client_ip", sa.String(length=64), nullable=True),
        sa.Column("client_device_id", sa.String(length=128), nullable=True),
        sa.Column("sms_vendor", sa.String(length=32), nullable=True),
        sa.Column("vendor_message_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sms_code_log_id"), "sms_code_log", ["id"], unique=False)
    op.create_index(op.f("ix_sms_code_log_phone"), "sms_code_log", ["phone"], unique=False)
    op.create_index(op.f("ix_sms_code_log_request_id"), "sms_code_log", ["request_id"], unique=True)
    op.create_index(op.f("ix_sms_code_log_scene"), "sms_code_log", ["scene"], unique=False)
    op.create_index(op.f("ix_sms_code_log_user_id"), "sms_code_log", ["user_id"], unique=False)
    op.create_index(op.f("ix_sms_code_log_tenant_id"), "sms_code_log", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_sms_code_log_verify_status"), "sms_code_log", ["verify_status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_sms_code_log_verify_status"), table_name="sms_code_log")
    op.drop_index(op.f("ix_sms_code_log_tenant_id"), table_name="sms_code_log")
    op.drop_index(op.f("ix_sms_code_log_user_id"), table_name="sms_code_log")
    op.drop_index(op.f("ix_sms_code_log_scene"), table_name="sms_code_log")
    op.drop_index(op.f("ix_sms_code_log_request_id"), table_name="sms_code_log")
    op.drop_index(op.f("ix_sms_code_log_phone"), table_name="sms_code_log")
    op.drop_index(op.f("ix_sms_code_log_id"), table_name="sms_code_log")
    op.drop_table("sms_code_log")

    op.drop_index("uk_sys_user_phone_country_phone", table_name="sys_user")
    op.drop_index("ix_sys_user_status", table_name="sys_user")
    op.drop_index("ix_sys_user_phone", table_name="sys_user")

    op.drop_column("sys_user", "login_fail_count")
    op.drop_column("sys_user", "locked_until")
    op.drop_column("sys_user", "last_login_at")
    op.drop_column("sys_user", "activated_at")
    op.drop_column("sys_user", "phone_verified_at")
    op.drop_column("sys_user", "status")
    op.drop_column("sys_user", "phone")
    op.drop_column("sys_user", "phone_country_code")
