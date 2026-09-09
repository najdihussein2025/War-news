"""add Harouf Arabic spelling alias

Revision ID: 20260909_0056
Revises: 20260909_0055
Create Date: 2026-09-09

Generated for manual deployment; do not run automatically.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260909_0056"
down_revision: Union[str, Sequence[str], None] = "20260909_0055"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO village_location_aliases (
                alias_text,
                alias_normalized,
                village_id,
                note
            )
            SELECT
                :alias_text,
                :alias_normalized,
                villages.id,
                :note
            FROM villages
            WHERE villages.acs_code = :parent_acs_code
            ON CONFLICT (alias_normalized) DO NOTHING
            """
        ).bindparams(
            alias_text="حاروف",
            alias_normalized="حاروف",
            parent_acs_code=71331,
            note="Common Arabic spelling of Harouf En-Nabatiyeh (ACS 71331).",
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM village_location_aliases AS aliases
            USING villages
            WHERE aliases.village_id = villages.id
              AND aliases.alias_normalized = :alias_normalized
              AND villages.acs_code = :parent_acs_code
            """
        ).bindparams(
            alias_normalized="حاروف",
            parent_acs_code=71331,
        )
    )
