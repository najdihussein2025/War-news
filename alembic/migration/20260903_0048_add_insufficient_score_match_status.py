"""add insufficient_score to match_status enum

Revision ID: 20260903_0048
Revises: 20260902_0047
"""

from alembic import op

revision = "20260903_0048"
down_revision = "20260902_0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE match_status ADD VALUE IF NOT EXISTS 'insufficient_score'"
    )


def downgrade() -> None:
    pass
