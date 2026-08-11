"""add villages and conditions

Revision ID: 20260811_0006
Revises: 20260811_0005
Create Date: 2026-08-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260811_0006"
down_revision: Union[str, Sequence[str], None] = "20260811_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "villages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("acs_code", sa.Integer(), nullable=False),
        sa.Column("acs_name", sa.String(), nullable=True),
        sa.Column("cad_name", sa.String(), nullable=True),
        sa.Column("ref_name_en", sa.String(), nullable=True),
        sa.Column("ref_name_ar", sa.String(), nullable=True),
        sa.Column("caza_en", sa.String(), nullable=True),
        sa.Column("caza_ar", sa.String(), nullable=True),
        sa.Column("mohafaza_en", sa.String(), nullable=True),
        sa.Column("mohafaza_ar", sa.String(), nullable=True),
        sa.Column("coord_x", sa.Float(), nullable=True),
        sa.Column("coord_y", sa.Float(), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("acs_code"),
    )

    op.create_table(
        "conditions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("action_en", sa.String(), nullable=False),
        sa.Column("action_ar", sa.String(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("action_ar"),
    )

    op.execute(
        "CREATE INDEX ix_villages_acs_name_trgm "
        "ON villages USING gin (acs_name gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_villages_ref_name_ar_trgm "
        "ON villages USING gin (ref_name_ar gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_conditions_action_ar_trgm "
        "ON conditions USING gin (action_ar gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_conditions_action_ar_trgm")
    op.execute("DROP INDEX IF EXISTS ix_villages_ref_name_ar_trgm")
    op.execute("DROP INDEX IF EXISTS ix_villages_acs_name_trgm")
    op.drop_table("conditions")
    op.drop_table("villages")
