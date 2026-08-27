"""add raw message processing claim lease fields

Revision ID: 20260827_0036
Revises: 20260827_0035
Create Date: 2026-08-27 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260827_0036"
down_revision = "20260827_0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "raw_messages",
        sa.Column("processing_claim_stage", sa.String(), nullable=True),
    )
    op.add_column(
        "raw_messages",
        sa.Column("processing_claimed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "raw_messages",
        sa.Column("processing_claimed_by", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_raw_messages_processing_claim_stage",
        "raw_messages",
        ["processing_claim_stage"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_raw_messages_processing_claim_stage", table_name="raw_messages")
    op.drop_column("raw_messages", "processing_claimed_by")
    op.drop_column("raw_messages", "processing_claimed_at")
    op.drop_column("raw_messages", "processing_claim_stage")
