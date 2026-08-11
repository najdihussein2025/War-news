"""add duplicate detection

Revision ID: 20260811_0009
Revises: 20260811_0008
Create Date: 2026-08-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

revision: str = "20260811_0009"
down_revision: Union[str, Sequence[str], None] = "20260811_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    match_type = postgresql.ENUM("exact", "soft", name="match_type", create_type=False)
    match_status = postgresql.ENUM(
        "pending",
        "confirmed_duplicate",
        "false_positive",
        name="match_status",
        create_type=False,
    )
    update_action = postgresql.ENUM(
        "create",
        "edit",
        "status_change",
        "delete",
        "undo",
        name="update_action",
        create_type=False,
    )
    match_type.create(op.get_bind(), checkfirst=True)
    match_status.create(op.get_bind(), checkfirst=True)
    update_action.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "incidents",
        sa.Column("khabar_embedding", Vector(384), nullable=True),
    )
    op.create_index(
        "ix_incidents_khabar_embedding_hnsw",
        "incidents",
        ["khabar_embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"khabar_embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "duplicate_matches",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("matched_incident_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("match_type", match_type, nullable=False),
        sa.Column("similarity_score", sa.Float(), nullable=True),
        sa.Column(
            "status",
            match_status,
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("resolved_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["matched_incident_id"],
            ["incidents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "incident_updates",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", update_action, nullable=False),
        sa.Column("old_values", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_values", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("performed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["performed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("incident_updates")
    op.drop_table("duplicate_matches")
    op.drop_index("ix_incidents_khabar_embedding_hnsw", table_name="incidents")
    op.drop_column("incidents", "khabar_embedding")

    postgresql.ENUM(name="update_action").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="match_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="match_type").drop(op.get_bind(), checkfirst=True)
