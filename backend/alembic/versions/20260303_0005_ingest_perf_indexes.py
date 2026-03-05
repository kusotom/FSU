"""add ingest performance indexes

Revision ID: 20260303_0005
Revises: 20260302_0004
Create Date: 2026-03-03 09:40:00
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260303_0005"
down_revision: Union[str, None] = "20260302_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_monitor_point_device_id_point_key_unique",
        "monitor_point",
        ["device_id", "point_key"],
        unique=True,
    )
    op.create_index(
        "ix_telemetry_history_point_id_collected_at",
        "telemetry_history",
        ["point_id", "collected_at"],
        unique=False,
    )
    op.create_index(
        "ix_alarm_event_point_id_status",
        "alarm_event",
        ["point_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_alarm_event_point_id_status", table_name="alarm_event")
    op.drop_index("ix_telemetry_history_point_id_collected_at", table_name="telemetry_history")
    op.drop_index("ix_monitor_point_device_id_point_key_unique", table_name="monitor_point")
