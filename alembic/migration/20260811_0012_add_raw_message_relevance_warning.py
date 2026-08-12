"""add raw message relevance warning

Revision ID: 20260811_0012
Revises: 20260811_0011
Create Date: 2026-08-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260811_0012"
down_revision: Union[str, Sequence[str], None] = "20260811_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "raw_messages",
        sa.Column(
            "low_confidence_relevance",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("raw_messages", "low_confidence_relevance")
