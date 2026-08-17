"""extend ingestion logs for status, errors, and retries

Revision ID: 20260817_0021
Revises: 20260817_0020
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260817_0021"
down_revision: Union[str, Sequence[str], None] = "20260817_0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ingestion_logs", sa.Column("status", sa.Text(), server_default="completed", nullable=False))
    op.add_column("ingestion_logs", sa.Column("error_message", sa.Text(), nullable=True))
    op.add_column("ingestion_logs", sa.Column("retry_of_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key("fk_ingestion_logs_retry_of", "ingestion_logs", "ingestion_logs", ["retry_of_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_ingestion_logs_created_at", "ingestion_logs", ["created_at"])
    op.create_index("ix_ingestion_logs_status", "ingestion_logs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_ingestion_logs_status", table_name="ingestion_logs")
    op.drop_index("ix_ingestion_logs_created_at", table_name="ingestion_logs")
    op.drop_constraint("fk_ingestion_logs_retry_of", "ingestion_logs", type_="foreignkey")
    op.drop_column("ingestion_logs", "retry_of_id")
    op.drop_column("ingestion_logs", "error_message")
    op.drop_column("ingestion_logs", "status")
