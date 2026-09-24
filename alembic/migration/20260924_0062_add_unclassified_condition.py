"""add unclassified condition review bucket

Revision ID: 20260924_0062
Revises: 20260923_0061
Create Date: 2026-09-24
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260924_0062"
down_revision: Union[str, Sequence[str], None] = "20260923_0061"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conditions = sa.table(
        "conditions",
        sa.column("action_en", sa.String()),
        sa.column("action_ar", sa.String()),
        sa.column("note", sa.Text()),
        sa.column("is_active", sa.Boolean()),
    )
    insert_stmt = postgresql.insert(conditions).values(
        action_en="Unclassified / Needs Review",
        action_ar="غير مصنف / بحاجة إلى مراجعة",
        note=(
            "Explicit condition-review bucket used when neither text evidence "
            "nor source metadata produces a usable condition."
        ),
        is_active=True,
    )
    op.execute(
        insert_stmt.on_conflict_do_update(
            index_elements=["action_ar"],
            set_={
                "action_en": insert_stmt.excluded.action_en,
                "note": insert_stmt.excluded.note,
                "is_active": True,
            },
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM conditions WHERE action_en = 'Unclassified / Needs Review'"
        )
    )
