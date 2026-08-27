"""add incident edit lock

Revision ID: 20260827_0038
Revises: 20260827_0037
Create Date: 2026-08-27

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260827_0038"
down_revision: Union[str, Sequence[str], None] = "20260827_0037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "incidents",
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.add_column(
        "incidents",
        sa.Column("locked_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "incidents",
        sa.Column("edit_lock_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_incidents_locked_by_user_id_users",
        "incidents",
        "users",
        ["locked_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_incidents_locked_by_user_id_users",
        "incidents",
        type_="foreignkey",
    )
    op.drop_column("incidents", "edit_lock_expires_at")
    op.drop_column("incidents", "locked_by_user_id")
    op.drop_column("incidents", "version")
