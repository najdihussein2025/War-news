"""guard every future incident soft-delete with a reason.

Revision ID: 20261008_0079
Revises: 20261008_0078
"""
from alembic import op

revision = "20261008_0079"
down_revision = "20261008_0078"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE incidents ADD CONSTRAINT ck_incidents_deleted_has_reason CHECK (is_deleted = false OR deleted_reason IS NOT NULL) NOT VALID")


def downgrade() -> None:
    op.drop_constraint("ck_incidents_deleted_has_reason", "incidents", type_="check")
