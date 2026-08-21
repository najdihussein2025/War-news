"""merge 20260819 heads

Revision ID: 20260821_0029
Revises: 20260819_0026, 20260819_0028
Create Date: 2026-08-21

"""
from typing import Sequence, Union


revision: str = "20260821_0029"
down_revision: Union[str, Sequence[str], None] = ("20260819_0026", "20260819_0028")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
