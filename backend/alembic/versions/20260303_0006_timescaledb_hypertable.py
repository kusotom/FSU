"""enable timescaledb hypertable for telemetry history

Revision ID: 20260303_0006
Revises: 20260303_0005
Create Date: 2026-03-03 19:20:00
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260303_0006"
down_revision: Union[str, None] = "20260303_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")

    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'telemetry_history_pkey'
              AND conrelid = 'telemetry_history'::regclass
          ) THEN
            ALTER TABLE telemetry_history DROP CONSTRAINT telemetry_history_pkey;
          END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'telemetry_history_pkey'
              AND conrelid = 'telemetry_history'::regclass
          ) THEN
            ALTER TABLE telemetry_history ADD CONSTRAINT telemetry_history_pkey PRIMARY KEY (id, collected_at);
          END IF;
        END
        $$;
        """
    )

    op.execute(
        """
        SELECT create_hypertable(
          'telemetry_history',
          'collected_at',
          if_not_exists => TRUE,
          migrate_data => TRUE,
          chunk_time_interval => INTERVAL '1 day'
        );
        """
    )

    op.execute(
        """
        ALTER TABLE telemetry_history SET (
          timescaledb.compress,
          timescaledb.compress_segmentby = 'point_id',
          timescaledb.compress_orderby = 'collected_at DESC'
        );
        """
    )
    op.execute(
        "SELECT add_compression_policy('telemetry_history', INTERVAL '7 days', if_not_exists => TRUE);"
    )
    op.execute(
        "SELECT add_retention_policy('telemetry_history', INTERVAL '90 days', if_not_exists => TRUE);"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        """
        DO $$
        BEGIN
          PERFORM remove_compression_policy('telemetry_history', if_exists => TRUE);
        EXCEPTION WHEN undefined_function THEN
          NULL;
        END
        $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
          PERFORM remove_retention_policy('telemetry_history', if_exists => TRUE);
        EXCEPTION WHEN undefined_function THEN
          NULL;
        END
        $$;
        """
    )
