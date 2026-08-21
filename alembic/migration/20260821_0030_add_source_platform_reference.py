"""add source platform reference

Revision ID: 20260821_0030
Revises: 20260821_0029
Create Date: 2026-08-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260821_0030"
down_revision: Union[str, Sequence[str], None] = "20260821_0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "source_platform",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("platform", "name", name="uq_source_platform_platform_name"),
    )
    op.add_column(
        "raw_messages",
        sa.Column("source_platform_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_raw_messages_source_platform_id",
        "raw_messages",
        "source_platform",
        ["source_platform_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_raw_messages_source_platform_id",
        "raw_messages",
        type_="foreignkey",
    )
    op.drop_column("raw_messages", "source_platform_id")
    op.drop_table("source_platform")
