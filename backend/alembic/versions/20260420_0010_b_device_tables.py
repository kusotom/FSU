"""b interface 2016 device tables

Revision ID: 20260420_0010
Revises: 20260312_0009
Create Date: 2026-04-20 22:15:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260420_0010"
down_revision: Union[str, None] = "20260312_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "b_device",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_code", sa.String(length=64), nullable=False),
        sa.Column("device_name", sa.String(length=128), nullable=False),
        sa.Column("site_code", sa.String(length=64), nullable=True),
        sa.Column("vendor", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("sn", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("software_version", sa.String(length=64), nullable=True),
        sa.Column("protocol_version", sa.String(length=16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_code", name="uk_b_device_device_code"),
    )
    op.create_index(op.f("ix_b_device_id"), "b_device", ["id"], unique=False)
    op.create_index(op.f("ix_b_device_device_code"), "b_device", ["device_code"], unique=False)
    op.create_index(op.f("ix_b_device_last_seen_at"), "b_device", ["last_seen_at"], unique=False)

    op.create_table(
        "b_device_config",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("config_key", sa.String(length=64), nullable=False),
        sa.Column("config_value", sa.String(length=512), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["b_device.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id", "config_key", name="uk_b_device_config_device_key"),
    )
    op.create_index(op.f("ix_b_device_config_id"), "b_device_config", ["id"], unique=False)
    op.create_index(op.f("ix_b_device_config_device_id"), "b_device_config", ["device_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_b_device_config_device_id"), table_name="b_device_config")
    op.drop_index(op.f("ix_b_device_config_id"), table_name="b_device_config")
    op.drop_table("b_device_config")

    op.drop_index(op.f("ix_b_device_last_seen_at"), table_name="b_device")
    op.drop_index(op.f("ix_b_device_device_code"), table_name="b_device")
    op.drop_index(op.f("ix_b_device_id"), table_name="b_device")
    op.drop_table("b_device")
