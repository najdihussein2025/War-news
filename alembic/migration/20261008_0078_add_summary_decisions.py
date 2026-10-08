"""add structured summary decision metadata

Revision ID: 20261008_0078
Revises: 20261008_0077
"""
from alembic import op
import sqlalchemy as sa

revision = "20261008_0078"
down_revision = "20261008_0077"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("incidents", sa.Column("decision_reason", sa.String(length=64), nullable=True))
    op.add_column("incidents", sa.Column("decision_source_summary_id", sa.BigInteger(), nullable=True))
    op.add_column("incidents", sa.Column("decision_ref_incident_id", sa.UUID(), nullable=True))
    op.add_column("incidents", sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("fk_incidents_decision_source_summary", "incidents", "summary_bulletins", ["decision_source_summary_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_incidents_decision_ref_incident", "incidents", "incidents", ["decision_ref_incident_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_incidents_decision_reason", "incidents", ["decision_reason"])


def downgrade() -> None:
    op.drop_index("ix_incidents_decision_reason", table_name="incidents")
    op.drop_constraint("fk_incidents_decision_ref_incident", "incidents", type_="foreignkey")
    op.drop_constraint("fk_incidents_decision_source_summary", "incidents", type_="foreignkey")
    op.drop_column("incidents", "decided_at")
    op.drop_column("incidents", "decision_ref_incident_id")
    op.drop_column("incidents", "decision_source_summary_id")
    op.drop_column("incidents", "decision_reason")
