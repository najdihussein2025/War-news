"""shared-toll owner, ordered group membership and admin total override

Revision ID: 20261019_0080
Revises: 20261008_0079
Create Date: 2026-10-19

Run manually: docker compose exec backend alembic upgrade head
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261019_0080"
down_revision: Union[str, Sequence[str], None] = "20261008_0079"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("bulletin_casualty_groups", sa.Column("owner_village_id", sa.Integer(), nullable=True))
    op.add_column(
        "bulletin_casualty_groups",
        sa.Column("owner_incident_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "bulletin_casualty_groups",
        sa.Column("total_overridden", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("bulletin_casualty_groups", sa.Column("total_override_reason", sa.Text(), nullable=True))
    op.add_column(
        "bulletin_casualty_groups",
        sa.Column("total_override_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "bulletin_casualty_groups",
        sa.Column("total_override_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_bulletin_casualty_groups_owner_village",
        "bulletin_casualty_groups", "villages", ["owner_village_id"], ["id"], ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_bulletin_casualty_groups_owner_incident",
        "bulletin_casualty_groups", "incidents", ["owner_incident_id"], ["id"], ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_bulletin_casualty_groups_override_user",
        "bulletin_casualty_groups", "users", ["total_override_by_user_id"], ["id"], ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_bulletin_casualty_groups_override_has_reason",
        "bulletin_casualty_groups",
        "total_overridden = false OR (total_override_reason IS NOT NULL AND total_override_at IS NOT NULL)",
    )

    op.create_table(
        "bulletin_casualty_group_members",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("group_id", sa.BigInteger(), nullable=False),
        sa.Column("village_id", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint("ordinal >= 0", name="ck_bulletin_group_member_ordinal"),
        sa.ForeignKeyConstraint(["group_id"], ["bulletin_casualty_groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["village_id"], ["villages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id", "village_id", name="uq_bulletin_group_member_village"),
        sa.UniqueConstraint("group_id", "ordinal", name="uq_bulletin_group_member_ordinal"),
    )
    op.create_index("ix_bulletin_group_members_incident", "bulletin_casualty_group_members", ["incident_id"])


def downgrade() -> None:
    op.drop_index("ix_bulletin_group_members_incident", table_name="bulletin_casualty_group_members")
    op.drop_table("bulletin_casualty_group_members")
    op.drop_constraint("ck_bulletin_casualty_groups_override_has_reason", "bulletin_casualty_groups", type_="check")
    op.drop_constraint("fk_bulletin_casualty_groups_override_user", "bulletin_casualty_groups", type_="foreignkey")
    op.drop_constraint("fk_bulletin_casualty_groups_owner_incident", "bulletin_casualty_groups", type_="foreignkey")
    op.drop_constraint("fk_bulletin_casualty_groups_owner_village", "bulletin_casualty_groups", type_="foreignkey")
    for column in (
        "total_override_at", "total_override_by_user_id", "total_override_reason",
        "total_overridden", "owner_incident_id", "owner_village_id",
    ):
        op.drop_column("bulletin_casualty_groups", column)
