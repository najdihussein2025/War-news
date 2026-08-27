"""add raw message match retry count

Revision ID: 20260827_0037
Revises: 20260827_0036
Create Date: 2026-08-27 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260827_0037"
down_revision = "20260827_0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "raw_messages",
        sa.Column(
            "match_retry_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("raw_messages", "match_retry_count")
