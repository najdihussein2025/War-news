"""add incident import support fields

Revision ID: 20260821_0031
Revises: 20260821_0030
Create Date: 2026-08-21

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260821_0031"
down_revision: Union[str, Sequence[str], None] = "20260821_0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("incidents", sa.Column("note_extra_2", sa.Text(), nullable=True))
    op.alter_column("incidents", "village_id", existing_type=sa.Integer(), nullable=True)
    op.alter_column("incidents", "condition_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.alter_column("incidents", "condition_id", existing_type=sa.Integer(), nullable=False)
    op.alter_column("incidents", "village_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("incidents", "note_extra_2")
