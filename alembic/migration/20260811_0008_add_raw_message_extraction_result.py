"""add raw message extraction result

Revision ID: 20260811_0008
Revises: 20260811_0007
Create Date: 2026-08-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260811_0008"
down_revision: Union[str, Sequence[str], None] = "20260811_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "raw_messages",
        sa.Column(
            "extraction_result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("raw_messages", "extraction_result")
