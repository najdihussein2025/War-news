"""add content source blocks

Revision ID: 20260814_0017
Revises: 20260814_0016
Create Date: 2026-08-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260814_0017"
down_revision: Union[str, Sequence[str], None] = "20260814_0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "content_source_blocks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_platform", sa.Text(), nullable=False),
        sa.Column("origin_account", sa.Text(), nullable=False),
        sa.Column(
            "is_blocked",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("blocked_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["blocked_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_platform",
            "origin_account",
            name="uq_content_source_blocks_platform_account",
        ),
    )
    op.create_index(
        "ix_content_source_blocks_platform_account",
        "content_source_blocks",
        ["source_platform", "origin_account"],
        unique=False,
    )
    op.add_column(
        "ingestion_logs",
        sa.Column(
            "messages_blocked",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("ingestion_logs", "messages_blocked")
    op.drop_index(
        "ix_content_source_blocks_platform_account",
        table_name="content_source_blocks",
    )
    op.drop_table("content_source_blocks")
