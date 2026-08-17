"""add persistent login logs

Revision ID: 20260817_0018
Revises: 20260814_0017
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260817_0018"
down_revision: Union[str, Sequence[str], None] = "20260814_0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "login_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("client_ip", sa.Text(), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_login_logs_created_at", "login_logs", ["created_at"])
    op.create_index("ix_login_logs_username", "login_logs", ["username"])


def downgrade() -> None:
    op.drop_index("ix_login_logs_username", table_name="login_logs")
    op.drop_index("ix_login_logs_created_at", table_name="login_logs")
    op.drop_table("login_logs")
