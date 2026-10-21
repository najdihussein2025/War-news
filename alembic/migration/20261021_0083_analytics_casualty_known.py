"""Analytics v2: casualty completeness column on the incident facts.

``casualty_known`` counts the incidents of a fact row whose ``casualty_status`` is set,
so the page can say "X% of incidents in this period have a casualty status" next to
every casualty number. Live rows are refilled by ``analytics_refresh_sweep --full``;
frozen archive rows are backfilled here from ``incidents_archive`` with the same grain
and the same bucket rule as ``app/analytics/services/status_buckets.py``.

Revision ID: 20261021_0083
Revises: 20261021_0082
Create Date: 2026-10-21
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261021_0083"
down_revision: Union[str, Sequence[str], None] = "20261021_0082"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "analytics_incident_facts",
        sa.Column("casualty_known", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute("""
        UPDATE analytics_incident_facts f
        SET casualty_known = x.n
        FROM (
            SELECT a.archive_batch, a.event_date, a.village_id, a.condition_id,
                   CASE WHEN a.verification_status = 'needs_verification'
                             OR NOT COALESCE(af.counts_in_headline, fb.counts_in_headline) THEN 'pending'
                        WHEN a.verification_status IN ('verified', 'auto_processed') THEN 'counted'
                        ELSE 'pending' END AS bucket,
                   count(*) FILTER (WHERE a.casualty_status IS NOT NULL) AS n
            FROM incidents_archive a
            CROSS JOIN (SELECT counts_in_headline FROM action_families WHERE code = 'unclassified') fb
            LEFT JOIN condition_families cf ON cf.condition_id = a.condition_id
            LEFT JOIN action_families af ON af.id = cf.family_id
            WHERE NOT a.is_deleted AND a.verification_status <> 'rejected'
            GROUP BY 1, 2, 3, 4, 5
        ) x
        WHERE f.source = 'archive' AND f.archive_batch = x.archive_batch AND f.event_date = x.event_date
          AND f.village_id IS NOT DISTINCT FROM x.village_id AND f.condition_id = x.condition_id
          AND f.bucket = x.bucket
    """)


def downgrade() -> None:
    op.drop_column("analytics_incident_facts", "casualty_known")
