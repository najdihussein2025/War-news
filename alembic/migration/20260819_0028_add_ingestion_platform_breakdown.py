"""add ingestion platform breakdown

Revision ID: 20260819_0028
Revises: 20260819_0027
Create Date: 2026-08-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260819_0028"
down_revision: Union[str, Sequence[str], None] = "20260819_0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ingestion_logs",
        sa.Column(
            "platform_breakdown",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    # Legacy webhook batches wrote raw_messages immediately before creating the
    # ingestion log. Match the closest batch timestamp and only backfill when
    # its message count exactly equals the run total, avoiding guessed data.
    op.execute(
        """
        WITH batch_times AS (
            SELECT l.id,
                   l.source_id,
                   l.messages_fetched,
                   (
                       SELECT max(r.received_at)
                       FROM raw_messages r
                       WHERE r.source_id = l.source_id
                         AND r.received_at <= l.started_at
                         AND r.received_at >= l.started_at - interval '1 second'
                   ) AS received_at
            FROM ingestion_logs l
            WHERE l.platform_breakdown = '{}'::jsonb
        ), platform_counts AS (
            SELECT b.id,
                   lower(coalesce(r.source_platform, 'unknown')) AS platform,
                   count(*)::integer AS message_count,
                   count(*) FILTER (
                       WHERE r.cnrs_classification ->> 'include' = 'false'
                   )::integer AS flagged_count
            FROM batch_times b
            JOIN raw_messages r
              ON r.source_id = b.source_id
             AND r.received_at = b.received_at
            GROUP BY b.id, lower(coalesce(r.source_platform, 'unknown'))
        ), exact_batches AS (
            SELECT b.id
            FROM batch_times b
            JOIN platform_counts p ON p.id = b.id
            GROUP BY b.id, b.messages_fetched
            HAVING sum(p.message_count) = b.messages_fetched
        ), payloads AS (
            SELECT p.id,
                   jsonb_object_agg(
                       p.platform,
                       jsonb_build_object(
                           'fetched', p.message_count,
                           'parsed', p.message_count,
                           'flagged', p.flagged_count,
                           'failed', 0,
                           'blocked', 0
                       )
                   ) AS breakdown
            FROM platform_counts p
            JOIN exact_batches e ON e.id = p.id
            GROUP BY p.id
        )
        UPDATE ingestion_logs l
        SET platform_breakdown = p.breakdown
        FROM payloads p
        WHERE l.id = p.id
        """
    )


def downgrade() -> None:
    op.drop_column("ingestion_logs", "platform_breakdown")
