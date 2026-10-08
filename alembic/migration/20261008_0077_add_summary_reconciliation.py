"""add summary reconciliation: incident origin, shadow result, header mappings, message status

Revision ID: 20261008_0077
Revises: 20261008_0076
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261008_0077"
down_revision = "20261008_0076"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Added in its own statement (precedent: 0064). The value is not used in this
    # migration, so it is safe inside the migration transaction on PostgreSQL 12+.
    op.execute("ALTER TYPE message_status ADD VALUE IF NOT EXISTS 'summary_handled'")

    sa.Enum("live", "summary", name="incident_origin").create(op.get_bind(), checkfirst=True)
    op.add_column(
        "incidents",
        sa.Column(
            "origin",
            postgresql.ENUM("live", "summary", name="incident_origin", create_type=False),
            nullable=False,
            server_default="live",
        ),
    )
    op.add_column("incidents", sa.Column("source_summary_item_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_incidents_source_summary_item_id",
        "incidents",
        "summary_items",
        ["source_summary_item_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_incidents_source_summary_item_id", "incidents", ["source_summary_item_id"])

    op.add_column("summary_bulletins", sa.Column("shadow_result", postgresql.JSONB(), nullable=True))

    op.create_table(
        "summary_header_mappings",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("header_text_normalized", sa.Text(), nullable=False, unique=True),
        sa.Column("condition_ids", postgresql.ARRAY(sa.Integer()), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("summary_header_mappings")
    op.drop_column("summary_bulletins", "shadow_result")
    op.drop_index("ix_incidents_source_summary_item_id", table_name="incidents")
    op.drop_constraint("fk_incidents_source_summary_item_id", "incidents", type_="foreignkey")
    op.drop_column("incidents", "source_summary_item_id")
    op.drop_column("incidents", "origin")
    sa.Enum(name="incident_origin").drop(op.get_bind(), checkfirst=True)
    # PostgreSQL cannot drop a value from message_status; 'summary_handled' stays (harmless).
