"""add held_for_review message status

Revision ID: 20260924_0064
Revises: 20260924_0063
Create Date: 2026-09-24
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "20260924_0064"
down_revision: Union[str, Sequence[str], None] = "20260924_0063"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE message_status ADD VALUE IF NOT EXISTS 'held_for_review'"
    )


def downgrade() -> None:
    raise NotImplementedError(
        "PostgreSQL does not support removing enum values; "
        "downgrade would require recreating message_status."
    )
