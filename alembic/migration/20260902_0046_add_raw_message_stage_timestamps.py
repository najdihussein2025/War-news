"""Add fixed, queryable raw-message pipeline stage timestamps.

Revision ID: 20260902_0046
Revises: 20260902_0045
"""
from alembic import op
import sqlalchemy as sa

revision = "20260902_0046"
down_revision = "20260902_0045"
branch_labels = None
depends_on = None

_COLUMNS = (
    "relevance_filtered_at", "dedup_checked_at", "extracted_at", "matched_at",
    "fast_path_completed_at", "tier2_completed_at", "embedded_at", "materialized_at",
)

def upgrade() -> None:
    for column in _COLUMNS:
        op.add_column("raw_messages", sa.Column(column, sa.DateTime(timezone=True), nullable=True))
        op.create_index(f"ix_raw_messages_{column}", "raw_messages", [column])

def downgrade() -> None:
    for column in reversed(_COLUMNS):
        op.drop_index(f"ix_raw_messages_{column}", table_name="raw_messages")
        op.drop_column("raw_messages", column)
