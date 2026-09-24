"""add incident_details.admin_cleared_gates

Revision ID: 20260924_0067
Revises: 20260924_0066
Create Date: 2026-09-24
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260924_0067"
down_revision: Union[str, Sequence[str], None] = "20260924_0066"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "incident_details",
        sa.Column(
            "admin_cleared_gates",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("incident_details", "admin_cleared_gates")
