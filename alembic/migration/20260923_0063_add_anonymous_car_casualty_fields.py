"""add anonymous car casualty fields for genderless vehicle tolls

Revision ID: 20260923_0063
Revises: 20260923_0062
Create Date: 2026-09-23
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260923_0063"
down_revision: Union[str, Sequence[str], None] = "20260923_0062"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "incident_details",
        sa.Column("cara_d", sa.Integer(), nullable=True),
    )
    op.add_column(
        "incident_details",
        sa.Column("cara_i", sa.Integer(), nullable=True),
    )
    # Existing rows that already stored genderless car tolls on card/cari
    # with no demographic splits: copy into the anonymous buckets.
    op.execute(
        """
        UPDATE incident_details
        SET cara_d = card
        WHERE card IS NOT NULL
          AND card > 0
          AND cara_d IS NULL
          AND COALESCE(carm_d, 0) = 0
          AND COALESCE(carf_d, 0) = 0
          AND COALESCE(carc_d, 0) = 0
        """
    )
    op.execute(
        """
        UPDATE incident_details
        SET cara_i = cari
        WHERE cari IS NOT NULL
          AND cari > 0
          AND cara_i IS NULL
          AND COALESCE(carm_i, 0) = 0
          AND COALESCE(carf_i, 0) = 0
          AND COALESCE(carc_i, 0) = 0
        """
    )


def downgrade() -> None:
    op.drop_column("incident_details", "cara_i")
    op.drop_column("incident_details", "cara_d")
