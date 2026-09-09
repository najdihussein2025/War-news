"""add bulletin casualty groups

Revision ID: 20260909_0055
Revises: 20260907_0054
Create Date: 2026-09-09

Run manually: docker compose exec backend alembic upgrade head
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260909_0055"
down_revision: Union[str, Sequence[str], None] = "20260907_0054"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    casualty_scope = postgresql.ENUM(
        "per_village_exact",
        "bulletin_aggregate",
        "unspecified",
        name="casualty_scope",
        create_type=False,
    )
    breakdown_status = postgresql.ENUM(
        "pending",
        "resolved",
        "expired",
        "n_a",
        name="bulletin_breakdown_status",
        create_type=False,
    )
    casualty_scope.create(op.get_bind(), checkfirst=True)
    breakdown_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "bulletin_casualty_groups",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("raw_message_id", sa.BigInteger(), nullable=False),
        sa.Column("village_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("casualty_scope", casualty_scope, nullable=False),
        sa.Column("total_deaths", sa.Integer(), nullable=True),
        sa.Column("total_injuries", sa.Integer(), nullable=True),
        sa.Column(
            "breakdown_status",
            breakdown_status,
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("window_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_raw_message_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "total_deaths IS NULL OR total_deaths >= 0",
            name="ck_bulletin_casualty_groups_total_deaths",
        ),
        sa.CheckConstraint(
            "total_injuries IS NULL OR total_injuries >= 0",
            name="ck_bulletin_casualty_groups_total_injuries",
        ),
        sa.ForeignKeyConstraint(
            ["raw_message_id"],
            ["raw_messages.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_raw_message_id"],
            ["raw_messages.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "raw_message_id",
            name="uq_bulletin_casualty_groups_raw_message",
        ),
    )
    op.create_index(
        "ix_bulletin_casualty_groups_pending_expiry",
        "bulletin_casualty_groups",
        ["breakdown_status", "window_expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_bulletin_casualty_groups_pending_expiry",
        table_name="bulletin_casualty_groups",
    )
    op.drop_table("bulletin_casualty_groups")
    postgresql.ENUM(name="bulletin_breakdown_status").drop(
        op.get_bind(),
        checkfirst=True,
    )
    postgresql.ENUM(name="casualty_scope").drop(
        op.get_bind(),
        checkfirst=True,
    )
