"""add routed_air_violation message status

Revision ID: 20260824_0033
Revises: 20260824_0032
Create Date: 2026-08-24

Terminal status for raw messages successfully routed to air_violations instead
of the incident pipeline. Generated for Najdi to apply; do not auto-run.

"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260824_0033"
down_revision: Union[str, Sequence[str], None] = "20260824_0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE message_status ADD VALUE IF NOT EXISTS 'routed_air_violation'"
    )


def downgrade() -> None:
    raise NotImplementedError(
        "PostgreSQL does not support removing enum values; "
        "downgrade would require recreating message_status."
    )
