"""add Debl and Jibbayn news-form village aliases

Revision ID: 20260923_0062
Revises: 20260923_0061
Create Date: 2026-09-23
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "20260923_0062"
down_revision: Union[str, Sequence[str], None] = "20260923_0061"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO village_location_aliases
            (alias_text, alias_normalized, village_id, note, requires_geo_context, is_active)
        SELECT alias_text, alias_normalized, v.id, note, false, true
        FROM (
            VALUES
                (
                    'دبل',
                    'دبل',
                    72281,
                    'Bare news form -> Debl. ACS Arabic is دبل امية.'
                ),
                (
                    'الجبين',
                    'الجبين',
                    62292,
                    'Definite-article news form -> Jibbayn. ACS Arabic is جبين.'
                )
        ) AS aliases(alias_text, alias_normalized, acs_code, note)
        JOIN villages v ON v.acs_code = aliases.acs_code
        ON CONFLICT (alias_normalized) DO UPDATE
        SET village_id = EXCLUDED.village_id,
            note = EXCLUDED.note,
            requires_geo_context = false,
            is_active = true
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM village_location_aliases
        WHERE alias_normalized IN ('دبل', 'الجبين')
        AND village_id IN (
            SELECT id FROM villages WHERE acs_code IN (72281, 62292)
        )
        """
    )
