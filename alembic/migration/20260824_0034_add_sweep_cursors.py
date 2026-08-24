"""add sweep_cursors watermark table

Revision ID: 20260824_0034
Revises: 20260824_0033
Create Date: 2026-08-24

Persisted live-sweep watermark so ingestion is processed automatically
without a stale hardcoded raw_messages.id cutoff. The live-sweep worker
inserts sweep_name='live_sweep_new_only' with last_processed_id=0 on
first run; no manual seed is required.

This file is generated for Najdi to apply; do not auto-run it from the agent.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260824_0034"
down_revision: Union[str, Sequence[str], None] = "20260824_0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sweep_cursors",
        sa.Column("sweep_name", sa.Text(), primary_key=True),
        sa.Column(
            "last_processed_id",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("sweep_cursors")
