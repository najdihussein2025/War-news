"""add audit logs

Revision ID: 20260817_0023
Revises: 20260817_0022
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260817_0023"
down_revision: Union[str, Sequence[str], None] = "20260817_0022"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table("audit_logs", sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True), sa.Column("action", sa.Text(), nullable=False), sa.Column("target_type", sa.Text(), nullable=False), sa.Column("target_id", sa.Text(), nullable=False), sa.Column("actor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True), sa.Column("actor_name", sa.Text(), nullable=False), sa.Column("client_ip", postgresql.INET(), nullable=True), sa.Column("old_values", postgresql.JSONB(), nullable=True), sa.Column("new_values", postgresql.JSONB(), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    for column in ("action", "target_type", "target_id", "created_at"): op.create_index(f"ix_audit_logs_{column}", "audit_logs", [column])
    op.execute(sa.text("INSERT INTO audit_logs (action, target_type, target_id, actor_name, new_values) VALUES ('system.audit_enabled', 'system', 'audit_logs', 'System', '{\"enabled\": true}'::jsonb)"))

def downgrade() -> None: op.drop_table("audit_logs")
