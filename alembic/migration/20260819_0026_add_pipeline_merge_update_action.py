"""add pipeline_merge update action

Revision ID: 20260819_0026
Revises: 20260819_0025
Create Date: 2026-08-19

"""
from typing import Sequence, Union

from alembic import op

revision: str = "20260819_0026"
down_revision: Union[str, Sequence[str], None] = "20260819_0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE update_action ADD VALUE IF NOT EXISTS 'pipeline_merge'")


def downgrade() -> None:
    pass
