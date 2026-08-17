"""merge heads

Revision ID: 2eccf58599e6
Revises: 20260814_0018, 20260817_0023
Create Date: 2026-08-17 10:33:34.072223

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '2eccf58599e6'
down_revision: Union[str, Sequence[str], None] = ('20260814_0018', '20260817_0023')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
