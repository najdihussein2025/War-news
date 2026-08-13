"""add CNRS classification metadata to raw messages

Revision ID: 20260813_0015
Revises: 20260813_0013, 20260813_0014
Create Date: 2026-08-13

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260813_0015"
down_revision: Union[str, Sequence[str], None] = (
    "20260813_0013",
    "20260813_0014",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "raw_messages",
        sa.Column("origin_platform", sa.Text(), nullable=True),
    )
    op.add_column(
        "raw_messages",
        sa.Column("origin_account", sa.Text(), nullable=True),
    )
    op.add_column(
        "raw_messages",
        sa.Column(
            "cnrs_classification",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("raw_messages", "cnrs_classification")
    op.drop_column("raw_messages", "origin_account")
    op.drop_column("raw_messages", "origin_platform")
