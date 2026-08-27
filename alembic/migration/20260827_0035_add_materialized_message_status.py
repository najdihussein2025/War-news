"""add materialized message status

Revision ID: 20260827_0035
Revises: 20260824_0034
Create Date: 2026-08-27

Terminal status for raw messages successfully materialized into incidents.
Generated for manual review and application; do not auto-run.

"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260827_0035"
down_revision: Union[str, Sequence[str], None] = "20260824_0034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE message_status ADD VALUE IF NOT EXISTS 'materialized'")


def downgrade() -> None:
    raise NotImplementedError(
        "PostgreSQL does not support removing enum values; "
        "downgrade would require recreating message_status."
    )
