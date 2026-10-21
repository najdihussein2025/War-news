"""add Latin "Hardinga" aliases for Haddatha (Bint Jbeil)

Tier 1 sometimes transliterates حداثا as "Hardinga" / "Harding"; trigram matching then
picked Hardine (Batroun, North) at 0.35-0.60. 25 live incidents (2026-08-27 to
2026-10-19) were placed in Hardine this way; every one of their texts names حداثا.
Evidence: Docs/analytics/geo-anomalies.md.

Revision ID: 20261021_0084
Revises: 20261021_0083
Create Date: 2026-10-21
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20261021_0084"
down_revision: Union[str, Sequence[str], None] = "20261021_0083"
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
                ('Hardinga', 'Hardinga', 'Latin transliteration of حداثا -> Haddatha (Bint Jbeil), not Hardine (Batroun).'),
                ('hardinga', 'hardinga', 'Latin transliteration of حداثا -> Haddatha (Bint Jbeil), not Hardine (Batroun).'),
                ('Harding', 'Harding', 'Latin transliteration of حداثا -> Haddatha (Bint Jbeil), not Hardine (Batroun).'),
                ('harding', 'harding', 'Latin transliteration of حداثا -> Haddatha (Bint Jbeil), not Hardine (Batroun).')
        ) AS aliases(alias_text, alias_normalized, note)
        JOIN villages v ON v.acs_code = 72231
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
        WHERE alias_normalized IN ('Hardinga', 'hardinga', 'Harding', 'harding')
        AND village_id IN (SELECT id FROM villages WHERE acs_code = 72231)
        """
    )
