"""remove derived historical login rows

Revision ID: 20260817_0020
Revises: 20260817_0019
"""
from typing import Sequence, Union

from alembic import op

revision: str = "20260817_0020"
down_revision: Union[str, Sequence[str], None] = "20260817_0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "DELETE FROM login_logs WHERE client_ip = 'Unavailable (historical)'"
    )


def downgrade() -> None:
    op.execute(
        """
        INSERT INTO login_logs (user_id, username, success, client_ip, created_at)
        SELECT id, username, true, 'Unavailable (historical)', last_login_at
        FROM users
        WHERE last_login_at IS NOT NULL
        """
    )
