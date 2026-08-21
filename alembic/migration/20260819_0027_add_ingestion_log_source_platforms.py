"""add ingestion log source platforms

Revision ID: 20260819_0027
Revises: 20260818_0024
Create Date: 2026-08-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260819_0027"
down_revision: Union[str, Sequence[str], None] = "20260818_0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ingestion_logs",
        sa.Column(
            "source_platforms",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.execute(
        sa.text(
            """
            UPDATE ingestion_logs AS log
            SET source_platforms = COALESCE(
                (
                    SELECT jsonb_agg(platform ORDER BY platform)
                    FROM (
                        SELECT DISTINCT lower(message.source_platform) AS platform
                        FROM raw_messages AS message
                        WHERE message.source_id = log.source_id
                          AND message.source_platform IS NOT NULL
                          AND message.received_at >= COALESCE(log.started_at, log.created_at) - interval '1 second'
                          AND message.received_at <= COALESCE(
                              log.finished_at,
                              log.created_at + interval '5 minutes'
                          )
                    ) AS platforms
                ),
                '[]'::jsonb
            )
            """
        )
    )


def downgrade() -> None:
    op.drop_column("ingestion_logs", "source_platforms")
