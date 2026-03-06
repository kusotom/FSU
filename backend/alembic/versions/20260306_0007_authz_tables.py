"""authz tables

Revision ID: 20260306_0007
Revises: 20260303_0006
Create Date: 2026-03-06 22:10:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260306_0007"
down_revision: Union[str, None] = "20260303_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sys_role_permission",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("permission_key", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["sys_role.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("role_id", "permission_key", name="uq_role_permission_key"),
    )
    op.create_index(op.f("ix_sys_role_permission_id"), "sys_role_permission", ["id"], unique=False)
    op.create_index(
        op.f("ix_sys_role_permission_permission_key"),
        "sys_role_permission",
        ["permission_key"],
        unique=False,
    )
    op.create_index(op.f("ix_sys_role_permission_role_id"), "sys_role_permission", ["role_id"], unique=False)

    op.create_table(
        "sys_user_data_scope",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("scope_value", sa.String(length=128), nullable=False),
        sa.Column("scope_name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "scope_type", "scope_value", name="uq_user_data_scope"),
    )
    op.create_index(op.f("ix_sys_user_data_scope_id"), "sys_user_data_scope", ["id"], unique=False)
    op.create_index(
        op.f("ix_sys_user_data_scope_scope_type"),
        "sys_user_data_scope",
        ["scope_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sys_user_data_scope_scope_value"),
        "sys_user_data_scope",
        ["scope_value"],
        unique=False,
    )
    op.create_index(op.f("ix_sys_user_data_scope_user_id"), "sys_user_data_scope", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_sys_user_data_scope_user_id"), table_name="sys_user_data_scope")
    op.drop_index(op.f("ix_sys_user_data_scope_scope_value"), table_name="sys_user_data_scope")
    op.drop_index(op.f("ix_sys_user_data_scope_scope_type"), table_name="sys_user_data_scope")
    op.drop_index(op.f("ix_sys_user_data_scope_id"), table_name="sys_user_data_scope")
    op.drop_table("sys_user_data_scope")

    op.drop_index(op.f("ix_sys_role_permission_role_id"), table_name="sys_role_permission")
    op.drop_index(op.f("ix_sys_role_permission_permission_key"), table_name="sys_role_permission")
    op.drop_index(op.f("ix_sys_role_permission_id"), table_name="sys_role_permission")
    op.drop_table("sys_role_permission")
