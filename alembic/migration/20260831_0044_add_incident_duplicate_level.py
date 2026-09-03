"""add incident duplicate level and score

Revision ID: 20260831_0044
Revises: 20260827_0043
Create Date: 2026-08-31
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260831_0044"
down_revision: Union[str, Sequence[str], None] = "20260827_0043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("incidents", sa.Column("duplicate_level", sa.String(length=16), nullable=True))
    op.add_column("incidents", sa.Column("duplicate_similarity_score", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("incidents", "duplicate_similarity_score")
    op.drop_column("incidents", "duplicate_level")
