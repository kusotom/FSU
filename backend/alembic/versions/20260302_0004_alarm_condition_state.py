"""add alarm condition state

Revision ID: 20260302_0004
Revises: 20260302_0003
Create Date: 2026-03-02 23:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260302_0004"
down_revision: Union[str, None] = "20260302_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "alarm_condition_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("point_id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("abnormal_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("normal_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["point_id"], ["monitor_point.id"]),
        sa.ForeignKeyConstraint(["rule_id"], ["alarm_rule.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("point_id", "rule_id", name="uq_alarm_condition_point_rule"),
    )
    op.create_index(
        op.f("ix_alarm_condition_state_point_id"),
        "alarm_condition_state",
        ["point_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_alarm_condition_state_rule_id"),
        "alarm_condition_state",
        ["rule_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_alarm_condition_state_rule_id"), table_name="alarm_condition_state")
    op.drop_index(op.f("ix_alarm_condition_state_point_id"), table_name="alarm_condition_state")
    op.drop_table("alarm_condition_state")
