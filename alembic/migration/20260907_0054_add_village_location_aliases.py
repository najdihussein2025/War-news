"""add village_location_aliases reference table

Revision ID: 20260907_0054
Revises: 20260907_0053
Create Date: 2026-09-07

Run manually: docker compose exec backend alembic upgrade head
Then seed: docker compose exec backend python -m app.core.seeds.seed_village_location_aliases
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260907_0054"
down_revision: Union[str, Sequence[str], None] = "20260907_0053"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "village_location_aliases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("alias_text", sa.String(), nullable=False),
        sa.Column("alias_normalized", sa.String(), nullable=False),
        sa.Column("village_id", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["village_id"],
            ["villages.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "alias_normalized",
            name="uq_village_location_aliases_norm",
        ),
    )
    op.create_index(
        "ix_village_location_aliases_village_id",
        "village_location_aliases",
        ["village_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_village_location_aliases_village_id",
        table_name="village_location_aliases",
    )
    op.drop_table("village_location_aliases")
