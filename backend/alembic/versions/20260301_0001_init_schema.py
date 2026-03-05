"""init schema

Revision ID: 20260301_0001
Revises:
Create Date: 2026-03-01 22:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260301_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "site",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("region", sa.String(length=128), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index(op.f("ix_site_id"), "site", ["id"], unique=False)

    op.create_table(
        "sys_role",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(op.f("ix_sys_role_id"), "sys_role", ["id"], unique=False)
    op.create_index(op.f("ix_sys_role_name"), "sys_role", ["name"], unique=True)

    op.create_table(
        "sys_user",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=128), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    op.create_index(op.f("ix_sys_user_id"), "sys_user", ["id"], unique=False)
    op.create_index(op.f("ix_sys_user_username"), "sys_user", ["username"], unique=True)

    op.create_table(
        "fsu_device",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("vendor", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["site_id"], ["site.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index(op.f("ix_fsu_device_code"), "fsu_device", ["code"], unique=True)
    op.create_index(op.f("ix_fsu_device_id"), "fsu_device", ["id"], unique=False)
    op.create_index(op.f("ix_fsu_device_site_id"), "fsu_device", ["site_id"], unique=False)

    op.create_table(
        "sys_user_role",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["sys_role.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("user_id", "role_id"),
    )

    op.create_table(
        "monitor_point",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("point_key", sa.String(length=64), nullable=False),
        sa.Column("point_name", sa.String(length=128), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("unit", sa.String(length=16), nullable=True),
        sa.Column("high_threshold", sa.Float(), nullable=True),
        sa.Column("low_threshold", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["fsu_device.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_monitor_point_device_id"), "monitor_point", ["device_id"], unique=False)
    op.create_index(op.f("ix_monitor_point_id"), "monitor_point", ["id"], unique=False)
    op.create_index(op.f("ix_monitor_point_point_key"), "monitor_point", ["point_key"], unique=False)

    op.create_table(
        "alarm_event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("point_id", sa.Integer(), nullable=False),
        sa.Column("alarm_code", sa.String(length=64), nullable=False),
        sa.Column("alarm_name", sa.String(length=128), nullable=False),
        sa.Column("alarm_level", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("trigger_value", sa.Float(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recovered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", sa.Integer(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["acknowledged_by"], ["sys_user.id"]),
        sa.ForeignKeyConstraint(["closed_by"], ["sys_user.id"]),
        sa.ForeignKeyConstraint(["device_id"], ["fsu_device.id"]),
        sa.ForeignKeyConstraint(["point_id"], ["monitor_point.id"]),
        sa.ForeignKeyConstraint(["site_id"], ["site.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_alarm_event_alarm_code"), "alarm_event", ["alarm_code"], unique=False)
    op.create_index(op.f("ix_alarm_event_device_id"), "alarm_event", ["device_id"], unique=False)
    op.create_index(op.f("ix_alarm_event_id"), "alarm_event", ["id"], unique=False)
    op.create_index(op.f("ix_alarm_event_point_id"), "alarm_event", ["point_id"], unique=False)
    op.create_index(op.f("ix_alarm_event_site_id"), "alarm_event", ["site_id"], unique=False)
    op.create_index(op.f("ix_alarm_event_status"), "alarm_event", ["status"], unique=False)

    op.create_table(
        "telemetry_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("point_id", sa.Integer(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["point_id"], ["monitor_point.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_telemetry_history_collected_at"), "telemetry_history", ["collected_at"], unique=False)
    op.create_index(op.f("ix_telemetry_history_id"), "telemetry_history", ["id"], unique=False)
    op.create_index(op.f("ix_telemetry_history_point_id"), "telemetry_history", ["point_id"], unique=False)

    op.create_table(
        "telemetry_latest",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("point_id", sa.Integer(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["point_id"], ["monitor_point.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("point_id", name="uq_latest_point"),
    )
    op.create_index(op.f("ix_telemetry_latest_id"), "telemetry_latest", ["id"], unique=False)
    op.create_index(op.f("ix_telemetry_latest_point_id"), "telemetry_latest", ["point_id"], unique=False)

    op.create_table(
        "alarm_action_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("alarm_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("operator_id", sa.Integer(), nullable=True),
        sa.Column("content", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["alarm_id"], ["alarm_event.id"]),
        sa.ForeignKeyConstraint(["operator_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_alarm_action_log_alarm_id"), "alarm_action_log", ["alarm_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_alarm_action_log_alarm_id"), table_name="alarm_action_log")
    op.drop_table("alarm_action_log")

    op.drop_index(op.f("ix_telemetry_latest_point_id"), table_name="telemetry_latest")
    op.drop_index(op.f("ix_telemetry_latest_id"), table_name="telemetry_latest")
    op.drop_table("telemetry_latest")

    op.drop_index(op.f("ix_telemetry_history_point_id"), table_name="telemetry_history")
    op.drop_index(op.f("ix_telemetry_history_id"), table_name="telemetry_history")
    op.drop_index(op.f("ix_telemetry_history_collected_at"), table_name="telemetry_history")
    op.drop_table("telemetry_history")

    op.drop_index(op.f("ix_alarm_event_status"), table_name="alarm_event")
    op.drop_index(op.f("ix_alarm_event_site_id"), table_name="alarm_event")
    op.drop_index(op.f("ix_alarm_event_point_id"), table_name="alarm_event")
    op.drop_index(op.f("ix_alarm_event_id"), table_name="alarm_event")
    op.drop_index(op.f("ix_alarm_event_device_id"), table_name="alarm_event")
    op.drop_index(op.f("ix_alarm_event_alarm_code"), table_name="alarm_event")
    op.drop_table("alarm_event")

    op.drop_index(op.f("ix_monitor_point_point_key"), table_name="monitor_point")
    op.drop_index(op.f("ix_monitor_point_id"), table_name="monitor_point")
    op.drop_index(op.f("ix_monitor_point_device_id"), table_name="monitor_point")
    op.drop_table("monitor_point")

    op.drop_table("sys_user_role")

    op.drop_index(op.f("ix_fsu_device_site_id"), table_name="fsu_device")
    op.drop_index(op.f("ix_fsu_device_id"), table_name="fsu_device")
    op.drop_index(op.f("ix_fsu_device_code"), table_name="fsu_device")
    op.drop_table("fsu_device")

    op.drop_index(op.f("ix_sys_user_username"), table_name="sys_user")
    op.drop_index(op.f("ix_sys_user_id"), table_name="sys_user")
    op.drop_table("sys_user")

    op.drop_index(op.f("ix_sys_role_name"), table_name="sys_role")
    op.drop_index(op.f("ix_sys_role_id"), table_name="sys_role")
    op.drop_table("sys_role")

    op.drop_index(op.f("ix_site_id"), table_name="site")
    op.drop_table("site")
