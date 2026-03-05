"""add alarm rules and heartbeat last_seen_at

Revision ID: 20260302_0003
Revises: 20260301_0002
Create Date: 2026-03-02 22:10:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260302_0003"
down_revision: Union[str, None] = "20260301_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("fsu_device", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_fsu_device_last_seen_at"), "fsu_device", ["last_seen_at"], unique=False)

    op.create_table(
        "alarm_rule",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rule_key", sa.String(length=64), nullable=False),
        sa.Column("rule_name", sa.String(length=128), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("metric_key", sa.String(length=64), nullable=True),
        sa.Column("alarm_code", sa.String(length=64), nullable=False),
        sa.Column("comparison", sa.String(length=24), nullable=False),
        sa.Column("threshold_value", sa.Float(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("alarm_level", sa.Integer(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rule_key"),
    )
    op.create_index(op.f("ix_alarm_rule_id"), "alarm_rule", ["id"], unique=False)
    op.create_index(op.f("ix_alarm_rule_rule_key"), "alarm_rule", ["rule_key"], unique=True)
    op.create_index(op.f("ix_alarm_rule_metric_key"), "alarm_rule", ["metric_key"], unique=False)
    op.create_index(op.f("ix_alarm_rule_alarm_code"), "alarm_rule", ["alarm_code"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_alarm_rule_alarm_code"), table_name="alarm_rule")
    op.drop_index(op.f("ix_alarm_rule_metric_key"), table_name="alarm_rule")
    op.drop_index(op.f("ix_alarm_rule_rule_key"), table_name="alarm_rule")
    op.drop_index(op.f("ix_alarm_rule_id"), table_name="alarm_rule")
    op.drop_table("alarm_rule")

    op.drop_index(op.f("ix_fsu_device_last_seen_at"), table_name="fsu_device")
    op.drop_column("fsu_device", "last_seen_at")
