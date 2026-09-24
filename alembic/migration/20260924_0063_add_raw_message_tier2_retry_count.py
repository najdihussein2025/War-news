"""add raw message tier2 retry count

Revision ID: 20260924_0063
Revises: 20260924_0062
Create Date: 2026-09-24
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260924_0063"
down_revision: Union[str, Sequence[str], None] = "20260924_0062"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "raw_messages",
        sa.Column(
            "tier2_retry_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("raw_messages", "tier2_retry_count")
