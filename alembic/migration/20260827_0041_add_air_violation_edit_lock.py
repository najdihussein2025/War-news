"""add air violation edit lock

Revision ID: 20260827_0041
Revises: 20260827_0040
Create Date: 2026-08-27

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260827_0041"
down_revision: Union[str, Sequence[str], None] = "20260827_0040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "air_violations",
        sa.Column("locked_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "air_violations",
        sa.Column("edit_lock_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_air_violations_locked_by_user_id_users",
        "air_violations",
        "users",
        ["locked_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_air_violations_locked_by_user_id_users",
        "air_violations",
        type_="foreignkey",
    )
    op.drop_column("air_violations", "edit_lock_expires_at")
    op.drop_column("air_violations", "locked_by_user_id")
