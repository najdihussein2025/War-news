"""add incident deleted_reason

Revision ID: 20260924_0066
Revises: 20260924_0065
Create Date: 2026-09-24

Existing soft-deleted rows keep deleted_reason NULL: their origin (admin vs
pipeline) is unknown, so orphan reconciliation leaves them alone.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260924_0066"
down_revision: Union[str, Sequence[str], None] = "20260924_0065"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "incidents",
        sa.Column("deleted_reason", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("incidents", "deleted_reason")
