"""add IP login throttling

Revision ID: 20260813_0014
Revises: 20260813_0013_login
Create Date: 2026-08-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260813_0014"
down_revision: Union[str, Sequence[str], None] = "20260813_0013_login"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "login_throttles",
        sa.Column("client_ip", sa.Text(), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("client_ip"),
    )


def downgrade() -> None:
    op.drop_table("login_throttles")
