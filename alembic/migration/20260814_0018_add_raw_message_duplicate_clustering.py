"""add raw message duplicate clustering

Revision ID: 20260814_0018
Revises: 20260814_0017
Create Date: 2026-08-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

revision: str = "20260814_0018"
down_revision: Union[str, Sequence[str], None] = "20260814_0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    trust_tier = postgresql.ENUM(
        "official",
        "trusted",
        "detail",
        name="trust_tier",
        create_type=False,
    )
    trust_tier.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "raw_messages",
        sa.Column("content_embedding", Vector(384), nullable=True),
    )
    op.create_index(
        "ix_raw_messages_content_embedding_hnsw",
        "raw_messages",
        ["content_embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"content_embedding": "vector_cosine_ops"},
    )

    op.add_column(
        "raw_messages",
        sa.Column("duplicate_of_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_raw_messages_duplicate_of_id",
        "raw_messages",
        "raw_messages",
        ["duplicate_of_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_raw_messages_duplicate_of_id",
        "raw_messages",
        ["duplicate_of_id"],
        unique=False,
    )

    channel_trust_tiers = op.create_table(
        "channel_trust_tiers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("channel_name", sa.String(), nullable=False),
        sa.Column("tier", trust_tier, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("channel_name"),
    )
    op.bulk_insert(
        channel_trust_tiers,
        [
            {"channel_name": "sameralhajali", "tier": "trusted"},
            {"channel_name": "bintjbeilnews", "tier": "trusted"},
            {"channel_name": "alichoeib1970", "tier": "trusted"},
            {"channel_name": "NNALeb", "tier": "official"},
            {"channel_name": "Janoubana", "tier": "detail"},
            {"channel_name": "nabatiehchannel", "tier": "detail"},
            {"channel_name": "alimortada963", "tier": "detail"},
        ],
    )


def downgrade() -> None:
    op.drop_table("channel_trust_tiers")

    op.drop_index("ix_raw_messages_duplicate_of_id", table_name="raw_messages")
    op.drop_constraint(
        "fk_raw_messages_duplicate_of_id",
        "raw_messages",
        type_="foreignkey",
    )
    op.drop_column("raw_messages", "duplicate_of_id")

    op.drop_index(
        "ix_raw_messages_content_embedding_hnsw",
        table_name="raw_messages",
    )
    op.drop_column("raw_messages", "content_embedding")

    postgresql.ENUM(name="trust_tier").drop(op.get_bind(), checkfirst=True)
