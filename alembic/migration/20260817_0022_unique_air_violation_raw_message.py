"""prevent duplicate air violation routing

Revision ID: 20260817_0022
Revises: 20260817_0021
"""
from typing import Sequence, Union

from alembic import op

revision: str = "20260817_0022"
down_revision: Union[str, Sequence[str], None] = "20260817_0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint("uq_air_violations_raw_message", "air_violations", ["raw_message_id"])


def downgrade() -> None:
    op.drop_constraint("uq_air_violations_raw_message", "air_violations", type_="unique")
