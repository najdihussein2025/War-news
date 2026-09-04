"""Add a database view containing only rejected news.

Revision ID: 20260903_0051
Revises: 20260903_0050
"""

from alembic import op


revision = "20260903_0051"
down_revision = "20260903_0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE VIEW rejected_news_view AS
        SELECT raw_messages.*
        FROM raw_messages
        WHERE status::text IN ('rejected', 'duplicate')
          AND COALESCE(message_datetime, received_at) >= CURRENT_TIMESTAMP - INTERVAL '7 days'
          AND (source_name IS NULL OR source_name <> 'Red Alert Lebanon')
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS rejected_news_view")
