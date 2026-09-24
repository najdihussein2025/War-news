"""add raw message failed_stage

Revision ID: 20260924_0065
Revises: 20260924_0064
Create Date: 2026-09-24
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260924_0065"
down_revision: Union[str, Sequence[str], None] = "20260924_0064"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "raw_messages",
        sa.Column("failed_stage", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("raw_messages", "failed_stage")
