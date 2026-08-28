"""add air violation version

Revision ID: 20260827_0040
Revises: 20260827_0037
Create Date: 2026-08-27

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260827_0040"
down_revision: Union[str, Sequence[str], None] = "20260827_0037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "air_violations",
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )


def downgrade() -> None:
    op.drop_column("air_violations", "version")
