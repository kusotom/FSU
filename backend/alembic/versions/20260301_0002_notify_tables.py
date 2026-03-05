"""add notify channel and policy

Revision ID: 20260301_0002
Revises: 20260301_0001
Create Date: 2026-03-01 22:45:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260301_0002"
down_revision: Union[str, None] = "20260301_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notify_channel",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("channel_type", sa.String(length=32), nullable=False),
        sa.Column("endpoint", sa.String(length=512), nullable=False),
        sa.Column("secret", sa.String(length=255), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(op.f("ix_notify_channel_id"), "notify_channel", ["id"], unique=False)
    op.create_index(op.f("ix_notify_channel_name"), "notify_channel", ["name"], unique=True)

    op.create_table(
        "notify_policy",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("min_alarm_level", sa.Integer(), nullable=False),
        sa.Column("event_types", sa.String(length=64), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["channel_id"], ["notify_channel.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(op.f("ix_notify_policy_channel_id"), "notify_policy", ["channel_id"], unique=False)
    op.create_index(op.f("ix_notify_policy_id"), "notify_policy", ["id"], unique=False)
    op.create_index(op.f("ix_notify_policy_name"), "notify_policy", ["name"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_notify_policy_name"), table_name="notify_policy")
    op.drop_index(op.f("ix_notify_policy_id"), table_name="notify_policy")
    op.drop_index(op.f("ix_notify_policy_channel_id"), table_name="notify_policy")
    op.drop_table("notify_policy")

    op.drop_index(op.f("ix_notify_channel_name"), table_name="notify_channel")
    op.drop_index(op.f("ix_notify_channel_id"), table_name="notify_channel")
    op.drop_table("notify_channel")
