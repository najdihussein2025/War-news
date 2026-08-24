"""allow fast-path duplicate_matches without a second incident

Revision ID: 20260824_0032
Revises: 20260821_0031
Create Date: 2026-08-24

Fast-path window skips never insert a second incidents row, so
duplicate_matches.matched_incident_id must be nullable and a raw_message_id
column records which message was skipped.

This file is generated for Najdi to apply; do not auto-run it from the agent.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260824_0032"
down_revision: Union[str, Sequence[str], None] = "20260821_0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "duplicate_matches",
        sa.Column("raw_message_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_duplicate_matches_raw_message_id",
        "duplicate_matches",
        "raw_messages",
        ["raw_message_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_duplicate_matches_raw_message_id",
        "duplicate_matches",
        ["raw_message_id"],
    )
    op.alter_column(
        "duplicate_matches",
        "matched_incident_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "duplicate_matches",
        "matched_incident_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.drop_index("ix_duplicate_matches_raw_message_id", table_name="duplicate_matches")
    op.drop_constraint(
        "fk_duplicate_matches_raw_message_id",
        "duplicate_matches",
        type_="foreignkey",
    )
    op.drop_column("duplicate_matches", "raw_message_id")
