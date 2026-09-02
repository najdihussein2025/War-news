"""Add GIN trigram index on raw_messages.raw_text for pre-extraction dedup.

Revision ID: 20260902_0044
Revises: 20260827_0043
Create Date: 2026-09-02

Run manually: docker compose exec backend alembic upgrade head
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260902_0044"
down_revision: Union[str, Sequence[str], None] = "20260827_0043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX ix_raw_messages_raw_text_trgm "
        "ON raw_messages USING gin (raw_text gin_trgm_ops)"
    )
    op.create_index(
        "ix_raw_messages_source_id_received_at",
        "raw_messages",
        ["source_id", "received_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_raw_messages_source_id_received_at", table_name="raw_messages")
    op.execute("DROP INDEX IF EXISTS ix_raw_messages_raw_text_trgm")
