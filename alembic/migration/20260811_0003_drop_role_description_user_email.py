"""drop role description and user email

Revision ID: 20260811_0003
Revises: 20260811_0002
Create Date: 2026-08-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260811_0003"
down_revision: Union[str, Sequence[str], None] = "20260811_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("users_email_key", "users", type_="unique")
    op.drop_column("users", "email")
    op.drop_column("roles", "description")


def downgrade() -> None:
    op.add_column(
        "roles",
        sa.Column("description", sa.Text(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("email", postgresql.CITEXT(), nullable=True),
    )
    op.execute("UPDATE users SET email = username WHERE email IS NULL")
    op.alter_column("users", "email", nullable=False)
    op.create_unique_constraint("users_email_key", "users", ["email"])
