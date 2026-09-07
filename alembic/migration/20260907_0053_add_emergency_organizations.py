"""add emergency_organizations reference table

Revision ID: 20260907_0053
Revises: 20260903_0052
Create Date: 2026-09-07

Run manually: docker compose exec backend alembic upgrade head
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260907_0053"
down_revision: Union[str, Sequence[str], None] = "20260903_0052"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "emergency_organizations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name_ar", sa.String(), nullable=False),
        sa.Column("name_en", sa.String(), nullable=False),
        sa.Column(
            "aliases",
            postgresql.ARRAY(sa.String()),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
        sa.Column("org_type", sa.String(), nullable=True),
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
        sa.UniqueConstraint("name_ar"),
    )

    op.execute(
        "CREATE INDEX ix_emergency_organizations_name_ar_trgm "
        "ON emergency_organizations USING gin (name_ar gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_emergency_organizations_name_ar_trgm")
    op.drop_table("emergency_organizations")
