"""add air violations

Revision ID: 20260814_0016
Revises: 20260813_0015
Create Date: 2026-08-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260814_0016"
down_revision: Union[str, Sequence[str], None] = "20260813_0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "air_violations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("raw_message_id", sa.BigInteger(), nullable=True),
        sa.Column("condition_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("caza_en", sa.String(), nullable=True),
        sa.Column("caza_ar", sa.String(), nullable=True),
        sa.Column("event_month", sa.String(), nullable=True),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("event_time", sa.Time(), nullable=True),
        sa.Column("khabar", sa.Text(), nullable=False),
        sa.Column("note_1", sa.Text(), nullable=True),
        sa.Column("note_2", sa.Text(), nullable=True),
        sa.Column("source_link", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["condition_id"],
            ["conditions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["raw_message_id"],
            ["raw_messages.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_air_violations_condition_id",
        "air_violations",
        ["condition_id"],
        unique=False,
    )
    op.create_index(
        "ix_air_violations_event_date",
        "air_violations",
        ["event_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_air_violations_event_date", table_name="air_violations")
    op.drop_index("ix_air_violations_condition_id", table_name="air_violations")
    op.drop_table("air_violations")
