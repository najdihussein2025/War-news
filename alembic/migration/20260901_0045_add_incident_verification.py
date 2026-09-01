"""add human incident verification workflow

Revision ID: 20260901_0045
Revises: 20260831_0044
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260901_0045"
down_revision = "20260831_0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("incidents", sa.Column("verification_status", sa.String(24), nullable=False, server_default="auto_processed"))
    op.add_column("incidents", sa.Column("verification_reason", sa.Text(), nullable=True))
    op.add_column("incidents", sa.Column("verified_by_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("incidents", sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("fk_incidents_verified_by_user_id", "incidents", "users", ["verified_by_user_id"], ["id"], ondelete="SET NULL")
    op.create_check_constraint("ck_incidents_verification_status", "incidents", "verification_status IN ('auto_processed','needs_verification','verified','rejected')")
    op.execute("""
        UPDATE incidents i SET verification_status = 'needs_verification'
        FROM raw_messages r
        WHERE r.id = i.raw_message_id AND (
          r.match_result->>'condition_match_status' = 'matched_low_confidence'
          OR EXISTS (SELECT 1 FROM jsonb_array_elements(COALESCE(r.match_result->'village_matches','[]'::jsonb)) v WHERE v->>'village_match_status' = 'matched_low_confidence')
        )
    """)


def downgrade() -> None:
    op.drop_constraint("ck_incidents_verification_status", "incidents", type_="check")
    op.drop_constraint("fk_incidents_verified_by_user_id", "incidents", type_="foreignkey")
    op.drop_column("incidents", "verified_at")
    op.drop_column("incidents", "verified_by_user_id")
    op.drop_column("incidents", "verification_reason")
    op.drop_column("incidents", "verification_status")
