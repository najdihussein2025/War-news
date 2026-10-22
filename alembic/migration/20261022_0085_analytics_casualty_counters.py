"""Analytics: casualty counters behind the "X of N incidents report casualties" note.

``casualty_known`` (0083) counts any set ``casualty_status``, including
``none_mentioned``, so it reads as ~99% next to a handful of deaths. Two counters
replace it on the page:

* ``casualty_explicit``      incidents with a stated, non-zero toll
                             (``total_deaths + total_injuries > 0``; a shared bulletin
                             toll counts once, on the incident that carries it)
* ``casualty_count_missing`` incidents whose report mentions casualties without a
                             number (``casualty_status = 'count_missing'``)

Live rows are refilled by ``python -m scripts.analytics_refresh_sweep --full`` after
this migration; frozen archive rows are backfilled here from ``incidents_archive`` with
the same grain and bucket rule as ``app/analytics/services/status_buckets.py`` (the
same statement shape as 0083).

Revision ID: 20261022_0085
Revises: 20261021_0084
Create Date: 2026-10-22
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261022_0085"
down_revision: Union[str, Sequence[str], None] = "20261021_0084"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "analytics_incident_facts",
        sa.Column("casualty_explicit", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "analytics_incident_facts",
        sa.Column("casualty_count_missing", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute("""
        UPDATE analytics_incident_facts f
        SET casualty_explicit = x.explicit, casualty_count_missing = x.missing
        FROM (
            SELECT a.archive_batch, a.event_date, a.village_id, a.condition_id,
                   CASE WHEN a.verification_status = 'needs_verification'
                             OR NOT COALESCE(af.counts_in_headline, fb.counts_in_headline) THEN 'pending'
                        WHEN a.verification_status IN ('verified', 'auto_processed') THEN 'counted'
                        ELSE 'pending' END AS bucket,
                   count(*) FILTER (WHERE COALESCE(a.total_deaths, 0) + COALESCE(a.total_injuries, 0) > 0) AS explicit,
                   count(*) FILTER (WHERE a.casualty_status = 'count_missing') AS missing
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
    op.drop_column("analytics_incident_facts", "casualty_count_missing")
    op.drop_column("analytics_incident_facts", "casualty_explicit")
