"""add raw_messages.extraction_retry_count

Revision ID: 20260819_0025
Revises: 20260818_0024
Create Date: 2026-08-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260819_0025"
down_revision: Union[str, Sequence[str], None] = "20260818_0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "raw_messages",
        sa.Column(
            "extraction_retry_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.execute(sa.text("UPDATE raw_messages SET extraction_retry_count = 0"))


def downgrade() -> None:
    op.drop_column("raw_messages", "extraction_retry_count")
