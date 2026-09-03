"""merge verification and pipeline observability heads

Revision ID: 20260903_0049
Revises: 20260901_0045, 20260903_0048
"""

from typing import Sequence, Union

revision: str = "20260903_0049"
down_revision: Union[str, Sequence[str], None] = (
    "20260901_0045",
    "20260903_0048",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
