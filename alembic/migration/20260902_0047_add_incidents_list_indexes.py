"""Add indexes for the incidents list read path.

Revision ID: 20260902_0047
Revises: 20260902_0046
"""

from alembic import op


revision = "20260902_0047"
down_revision = "20260902_0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Active incident filters always exclude soft-deleted rows.
    op.create_index(
        "ix_incidents_active_event_date",
        "incidents",
        ["event_date"],
        postgresql_where="is_deleted IS FALSE",
    )
    op.create_index(
        "ix_incidents_active_duplicate_raw_message",
        "incidents",
        ["raw_message_id"],
        postgresql_where="is_deleted IS FALSE AND duplicate_flag IS TRUE",
    )
    # Supports status filtering and the raw-message portion of newest-first reads.
    op.create_index(
        "ix_raw_messages_status_received_at",
        "raw_messages",
        ["status", "received_at"],
        postgresql_using="btree",
    )


def downgrade() -> None:
    op.drop_index("ix_raw_messages_status_received_at", table_name="raw_messages")
    op.drop_index(
        "ix_incidents_active_duplicate_raw_message", table_name="incidents"
    )
    op.drop_index("ix_incidents_active_event_date", table_name="incidents")
