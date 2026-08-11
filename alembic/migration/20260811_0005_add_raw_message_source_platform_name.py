"""add raw message source platform and name

Revision ID: 20260811_0005
Revises: 20260811_0004
Create Date: 2026-08-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260811_0005"
down_revision: Union[str, Sequence[str], None] = "20260811_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "raw_messages",
        sa.Column("source_platform", sa.String(), nullable=True),
    )
    op.add_column(
        "raw_messages",
        sa.Column("source_name", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_raw_messages_source_platform",
        "raw_messages",
        ["source_platform"],
    )
    op.create_index(
        "ix_raw_messages_source_name",
        "raw_messages",
        ["source_name"],
    )


def downgrade() -> None:
    op.drop_index("ix_raw_messages_source_name", table_name="raw_messages")
    op.drop_index("ix_raw_messages_source_platform", table_name="raw_messages")
    op.drop_column("raw_messages", "source_name")
    op.drop_column("raw_messages", "source_platform")
