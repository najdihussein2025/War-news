"""add summary bulletin shadow-flow tables

Revision ID: 20261008_0076
Revises: 20261005_0075
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261008_0076"
down_revision = "20261005_0075"
branch_labels = None
depends_on = None

ENUMS = {
    "summary_kind": ("full_day", "partial", "unknown"),
    "summary_status": ("detected", "parsed", "needs_review", "awaiting_window", "reconciling", "reconciled", "skipped_repost", "failed"),
    "summary_modifier": ("none", "outskirts", "between"),
    "summary_item_origin": ("parser", "llm_crosscheck"),
    "summary_resolution": ("resolved", "unresolved_location", "unknown_header"),
    "summary_reconciliation_status": ("pending", "matched", "created", "ambiguous"),
    "summary_review_status": ("open", "resolved", "dismissed"),
}


def enum_type(name: str) -> postgresql.ENUM:
    """Return a migration-only enum that never emits CREATE TYPE implicitly."""
    return postgresql.ENUM(*ENUMS[name], name=name, create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    for name in ENUMS:
        enum_type(name).create(bind, checkfirst=True)
    op.create_table("summary_bulletins", sa.Column("id", sa.BigInteger(), primary_key=True), sa.Column("raw_message_id", sa.BigInteger(), sa.ForeignKey("raw_messages.id", ondelete="CASCADE"), nullable=False, unique=True), sa.Column("source_id", sa.BigInteger(), sa.ForeignKey("sources.id", ondelete="SET NULL")), sa.Column("channel", sa.Text()), sa.Column("kind", enum_type("summary_kind"), nullable=False), sa.Column("window_start", sa.DateTime(timezone=True)), sa.Column("window_end", sa.DateTime(timezone=True)), sa.Column("window_basis", sa.Text()), sa.Column("fingerprint", sa.Text(), nullable=False), sa.Column("canonical_summary_id", sa.BigInteger(), sa.ForeignKey("summary_bulletins.id", ondelete="SET NULL")), sa.Column("status", enum_type("summary_status"), nullable=False), sa.Column("process_after", sa.DateTime(timezone=True)), sa.Column("parser_version", sa.Text()), sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"), sa.Column("last_error", sa.Text()), sa.Column("hidden", sa.Boolean(), nullable=False, server_default=sa.text("false")), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_summary_bulletins_fingerprint", "summary_bulletins", ["fingerprint"])
    op.create_table("summary_items", sa.Column("id", sa.BigInteger(), primary_key=True), sa.Column("summary_id", sa.BigInteger(), sa.ForeignKey("summary_bulletins.id", ondelete="CASCADE"), nullable=False), sa.Column("position", sa.Integer(), nullable=False), sa.Column("header_text", sa.Text()), sa.Column("condition_id", sa.BigInteger(), sa.ForeignKey("conditions.id", ondelete="SET NULL")), sa.Column("location_text", sa.Text(), nullable=False), sa.Column("primary_village_id", sa.BigInteger(), sa.ForeignKey("villages.id", ondelete="SET NULL")), sa.Column("secondary_village_id", sa.BigInteger(), sa.ForeignKey("villages.id", ondelete="SET NULL")), sa.Column("modifier", enum_type("summary_modifier"), nullable=False), sa.Column("reported_count", sa.Integer()), sa.Column("evidence_span", sa.Text(), nullable=False), sa.Column("origin", enum_type("summary_item_origin"), nullable=False), sa.Column("resolution", enum_type("summary_resolution"), nullable=False), sa.Column("reconciliation_status", enum_type("summary_reconciliation_status"), nullable=False, server_default="pending"), sa.Column("matched_incident_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("incidents.id", ondelete="SET NULL")), sa.Column("created_incident_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("incidents.id", ondelete="SET NULL")), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_summary_items_summary_id", "summary_items", ["summary_id"])
    op.create_index("ix_summary_items_village_condition", "summary_items", ["primary_village_id", "condition_id"])
    op.create_table("summary_review_tasks", sa.Column("id", sa.BigInteger(), primary_key=True), sa.Column("summary_id", sa.BigInteger(), sa.ForeignKey("summary_bulletins.id", ondelete="CASCADE"), nullable=False, unique=True), sa.Column("reasons", postgresql.JSONB(), nullable=False), sa.Column("status", enum_type("summary_review_status"), nullable=False), sa.Column("resolved_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")), sa.Column("resolved_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))


def downgrade() -> None:
    op.drop_table("summary_review_tasks")
    op.drop_index("ix_summary_items_village_condition", table_name="summary_items")
    op.drop_index("ix_summary_items_summary_id", table_name="summary_items")
    op.drop_table("summary_items")
    op.drop_index("ix_summary_bulletins_fingerprint", table_name="summary_bulletins")
    op.drop_table("summary_bulletins")
    bind = op.get_bind()
    for name in reversed(ENUMS):
        enum_type(name).drop(bind, checkfirst=True)
