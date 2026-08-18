"""add incidents.details_pending

Revision ID: 20260818_0024
Revises: 2eccf58599e6
Create Date: 2026-08-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260818_0024"
down_revision: Union[str, Sequence[str], None] = "2eccf58599e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "incidents",
        sa.Column(
            "details_pending",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.execute(sa.text("UPDATE incidents SET details_pending = false"))


def downgrade() -> None:
    op.drop_column("incidents", "details_pending")
