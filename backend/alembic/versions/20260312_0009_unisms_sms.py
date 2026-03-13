"""unisms sms code and delivery tables

Revision ID: 20260312_0009
Revises: 20260312_0008
Create Date: 2026-03-12 21:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260312_0009"
down_revision: Union[str, None] = "20260312_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sys_user", sa.Column("phone_login_enabled", sa.Boolean(), nullable=True))
    op.execute("UPDATE sys_user SET phone_login_enabled = TRUE WHERE phone_login_enabled IS NULL")
    with op.batch_alter_table("sys_user") as batch_op:
        batch_op.alter_column("phone_login_enabled", existing_type=sa.Boolean(), nullable=False)

    op.create_table(
        "auth_sms_code",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("scene", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("tenant_id", sa.Integer(), nullable=True),
        sa.Column("phone_country_code", sa.String(length=8), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("phone_e164", sa.String(length=24), nullable=False),
        sa.Column("code_hash", sa.String(length=128), nullable=False),
        sa.Column("code_salt", sa.String(length=64), nullable=False),
        sa.Column("code_length", sa.Integer(), nullable=False),
        sa.Column("send_status", sa.String(length=16), nullable=False),
        sa.Column("verify_status", sa.String(length=16), nullable=False),
        sa.Column("verify_fail_count", sa.Integer(), nullable=False),
        sa.Column("max_verify_fail_count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("client_ip", postgresql.INET(), nullable=True),
        sa.Column("client_user_agent", sa.String(length=255), nullable=True),
        sa.Column("client_device_id", sa.String(length=128), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_template_id", sa.String(length=64), nullable=True),
        sa.Column("provider_signature", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", name="uk_auth_sms_code_request_id"),
    )
    op.create_index("ix_auth_sms_code_phone_e164", "auth_sms_code", ["phone_e164"], unique=False)
    op.create_index("ix_auth_sms_code_scene", "auth_sms_code", ["scene"], unique=False)
    op.create_index("ix_auth_sms_code_send_status", "auth_sms_code", ["send_status"], unique=False)
    op.create_index("ix_auth_sms_code_verify_status", "auth_sms_code", ["verify_status"], unique=False)
    op.create_index("ix_auth_sms_code_expires_at", "auth_sms_code", ["expires_at"], unique=False)
    op.create_index("ix_auth_sms_code_user_id", "auth_sms_code", ["user_id"], unique=False)
    op.create_index("ix_auth_sms_code_tenant_id", "auth_sms_code", ["tenant_id"], unique=False)

    op.create_table(
        "auth_sms_delivery_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sms_code_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_message_id", sa.String(length=64), nullable=False),
        sa.Column("provider_action", sa.String(length=64), nullable=False),
        sa.Column("phone_e164", sa.String(length=24), nullable=False),
        sa.Column("submit_http_status", sa.Integer(), nullable=True),
        sa.Column("submit_code", sa.String(length=32), nullable=True),
        sa.Column("submit_message", sa.String(length=255), nullable=True),
        sa.Column("submit_status", sa.String(length=16), nullable=False),
        sa.Column("upstream", sa.String(length=64), nullable=True),
        sa.Column("message_count", sa.Integer(), nullable=True),
        sa.Column("price", sa.Numeric(18, 6), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("submit_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("submit_response", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("dlr_status", sa.String(length=32), nullable=True),
        sa.Column("dlr_error_code", sa.String(length=64), nullable=True),
        sa.Column("dlr_error_message", sa.Text(), nullable=True),
        sa.Column("submit_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("done_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_webhook_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_webhook_headers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("webhook_verified", sa.Boolean(), nullable=False),
        sa.Column("webhook_received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["sms_code_id"], ["auth_sms_code.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_message_id", name="uk_auth_sms_delivery_provider_msg"),
    )
    op.create_index("ix_auth_sms_delivery_sms_code_id", "auth_sms_delivery_log", ["sms_code_id"], unique=False)
    op.create_index("ix_auth_sms_delivery_phone_e164", "auth_sms_delivery_log", ["phone_e164"], unique=False)
    op.create_index("ix_auth_sms_delivery_submit_status", "auth_sms_delivery_log", ["submit_status"], unique=False)
    op.create_index("ix_auth_sms_delivery_dlr_status", "auth_sms_delivery_log", ["dlr_status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_auth_sms_delivery_dlr_status", table_name="auth_sms_delivery_log")
    op.drop_index("ix_auth_sms_delivery_submit_status", table_name="auth_sms_delivery_log")
    op.drop_index("ix_auth_sms_delivery_phone_e164", table_name="auth_sms_delivery_log")
    op.drop_index("ix_auth_sms_delivery_sms_code_id", table_name="auth_sms_delivery_log")
    op.drop_table("auth_sms_delivery_log")

    op.drop_index("ix_auth_sms_code_tenant_id", table_name="auth_sms_code")
    op.drop_index("ix_auth_sms_code_user_id", table_name="auth_sms_code")
    op.drop_index("ix_auth_sms_code_expires_at", table_name="auth_sms_code")
    op.drop_index("ix_auth_sms_code_verify_status", table_name="auth_sms_code")
    op.drop_index("ix_auth_sms_code_send_status", table_name="auth_sms_code")
    op.drop_index("ix_auth_sms_code_scene", table_name="auth_sms_code")
    op.drop_index("ix_auth_sms_code_phone_e164", table_name="auth_sms_code")
    op.drop_table("auth_sms_code")

    op.drop_column("sys_user", "phone_login_enabled")
