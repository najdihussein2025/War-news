"""add account version and edit lock

Revision ID: 20260827_0039
Revises: 20260827_0038
Create Date: 2026-08-27

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260827_0039"
down_revision: Union[str, Sequence[str], None] = "20260827_0038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column(
        "users",
        sa.Column("admin_edit_locked_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("admin_edit_lock_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_users_admin_edit_locked_by_user_id_users",
        "users",
        "users",
        ["admin_edit_locked_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_users_admin_edit_locked_by_user_id_users",
        "users",
        type_="foreignkey",
    )
    op.drop_column("users", "admin_edit_lock_expires_at")
    op.drop_column("users", "admin_edit_locked_by_user_id")
    op.drop_column("users", "version")
