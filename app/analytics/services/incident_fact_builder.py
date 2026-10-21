"""Build ``analytics_incident_facts`` rows from live incidents or from an archive batch.

Casualties
    ``total_deaths`` / ``total_injuries`` are the headline totals (NULL counts as 0);
    the legacy ``deaths`` / ``injuries`` columns are never read. Demographics come
    from ``incident_details``; ``unspecified = max(total - male - female - children, 0)``
    per incident. A shared bulletin toll lives on its owner incident only (the
    other members keep NULL casualties), so summing incidents counts it once;
    ``aggregate_only_incidents`` counts the incidents carrying such a toll so the
    UI can label it "not attributed to a specific village".
    ``casualty_known`` counts incidents whose ``casualty_status`` is set (the
    casualty-completeness note next to every casualty number).

Geography
    villages.admin_area_code -> admin_areas gives the village/caza/mohafaza codes.
    A village without a code keeps its ``village_id`` and NULL codes: it counts in
    national totals only.

Bucketing is decided by ``status_buckets`` (the one definition of "headline").
Live facts skip any incident id present in ``incidents_archive`` so the archive and
the live table never double count while both still hold the same rows.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.analytics.models.facts import SOURCE_ARCHIVE, SOURCE_LIVE
from app.analytics.services.status_buckets import bucket_sql

logger = logging.getLogger(__name__)

FALLBACK_FAMILY_CODE = "unclassified"

_SRC_COLUMNS = """
    {p}.id, {p}.event_date, {p}.village_id, {p}.condition_id, {p}.verification_status,
    {p}.is_deleted, {p}.total_deaths, {p}.total_injuries, {p}.casualty_status,
    {d}.male_d, {d}.male_i, {d}.female_d, {d}.female_i, {d}.children_d, {d}.children_i
"""

_LIVE_SOURCE = (
    "SELECT " + _SRC_COLUMNS.format(p="i", d="d") + """
    FROM incidents i
    LEFT JOIN incident_details d ON d.incident_id = i.id
    WHERE (CAST(:all_dates AS boolean) OR i.event_date = ANY(CAST(:dates AS date[])))
      AND NOT EXISTS (SELECT 1 FROM incidents_archive a WHERE a.id = i.id)
"""
)
_ARCHIVE_SOURCE = (
    "SELECT " + _SRC_COLUMNS.format(p="a", d="a") + """
    FROM incidents_archive a
    WHERE a.archive_batch = :batch
"""
)

_INSERT_TEMPLATE = """
INSERT INTO analytics_incident_facts (
    event_date, admin_village_code, caza_code, mohafaza_code, village_id, condition_id, family_id,
    bucket, source, archive_batch, incidents,
    deaths_total, deaths_male, deaths_female, deaths_children, deaths_unspecified,
    injuries_total, injuries_male, injuries_female, injuries_children, injuries_unspecified,
    aggregate_only_incidents, casualty_known, refreshed_at
)
WITH src AS ({source}),
resolved AS (
    SELECT s.*,
           COALESCE(cf.family_id, fb.id) AS family_id,
           COALESCE(af.counts_in_headline, fb.counts_in_headline) AS family_counts,
           aa.code AS admin_village_code, aa.caza_code, aa.mohafaza_code
    FROM src s
    CROSS JOIN (SELECT id, counts_in_headline FROM action_families WHERE code = :fallback_family) fb
    LEFT JOIN condition_families cf ON cf.condition_id = s.condition_id
    LEFT JOIN action_families af ON af.id = cf.family_id
    LEFT JOIN villages v ON v.id = s.village_id
    LEFT JOIN admin_areas aa ON aa.code = v.admin_area_code
    WHERE s.condition_id IS NOT NULL
),
bucketed AS (
    SELECT r.*, {bucket} AS bucket
    FROM resolved r
)
SELECT event_date, admin_village_code, caza_code, mohafaza_code, village_id, condition_id, family_id,
       bucket, :source, :batch_value, count(*),
       sum(COALESCE(total_deaths, 0)),
       sum(COALESCE(male_d, 0)), sum(COALESCE(female_d, 0)), sum(COALESCE(children_d, 0)),
       sum(GREATEST(COALESCE(total_deaths, 0) - COALESCE(male_d, 0) - COALESCE(female_d, 0)
                    - COALESCE(children_d, 0), 0)),
       sum(COALESCE(total_injuries, 0)),
       sum(COALESCE(male_i, 0)), sum(COALESCE(female_i, 0)), sum(COALESCE(children_i, 0)),
       sum(GREATEST(COALESCE(total_injuries, 0) - COALESCE(male_i, 0) - COALESCE(female_i, 0)
                    - COALESCE(children_i, 0), 0)),
       count(*) FILTER (WHERE casualty_status = 'aggregate_only'),
       count(*) FILTER (WHERE casualty_status IS NOT NULL),
       now()
FROM bucketed
WHERE bucket IS NOT NULL
GROUP BY event_date, admin_village_code, caza_code, mohafaza_code, village_id, condition_id,
         family_id, bucket
"""


class ReferenceDataMissing(RuntimeError):
    """The action families have not been loaded (run scripts.analytics_load_reference)."""


def _insert_sql(source: str) -> str:
    return _INSERT_TEMPLATE.format(
        source=source,
        bucket=bucket_sql("status_value", "is_deleted", "family_counts").replace(
            "status_value", "verification_status"
        ),
    )


def _require_reference(db: Session) -> None:
    if not db.execute(
        text("SELECT 1 FROM action_families WHERE code = :code"), {"code": FALLBACK_FAMILY_CODE}
    ).first():
        raise ReferenceDataMissing(
            "action_families is empty; run `python -m scripts.analytics_load_reference --apply` first"
        )


def _log_data_gaps(db: Session, source: str, params: dict) -> None:
    unmapped = db.execute(text(f"""
        WITH src AS ({source})
        SELECT count(*) FROM src s
        WHERE s.condition_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM condition_families cf WHERE cf.condition_id = s.condition_id)
    """), params).scalar_one()
    if unmapped:
        logger.warning(
            "analytics: %s incidents use a condition with no action family; counted as '%s'",
            unmapped, FALLBACK_FAMILY_CODE,
        )
    no_code = db.execute(text(f"""
        WITH src AS ({source})
        SELECT count(*) FROM src s JOIN villages v ON v.id = s.village_id
        WHERE v.admin_area_code IS NULL
    """), params).scalar_one()
    if no_code:
        logger.warning(
            "analytics: %s incidents are in villages without an admin_area_code "
            "(national totals only)", no_code,
        )


def delete_live_facts(db: Session, dates: Iterable[date] | None) -> int:
    if dates is None:
        return db.execute(text("DELETE FROM analytics_incident_facts WHERE source = 'live'")).rowcount
    return db.execute(
        text("DELETE FROM analytics_incident_facts WHERE source = 'live' "
             "AND event_date = ANY(CAST(:dates AS date[]))"),
        {"dates": sorted(set(dates))},
    ).rowcount


def insert_live_facts(db: Session, dates: Iterable[date] | None) -> int:
    """Insert live fact rows for ``dates`` (``None`` = every date). Caller deleted the old rows."""
    _require_reference(db)
    date_list = sorted(set(dates)) if dates is not None else []
    params = {"all_dates": dates is None, "dates": date_list}
    _log_data_gaps(db, _LIVE_SOURCE, params)
    result = db.execute(
        text(_insert_sql(_LIVE_SOURCE)),
        {**params, "source": SOURCE_LIVE, "batch_value": None, "fallback_family": FALLBACK_FAMILY_CODE},
    )
    return result.rowcount


def insert_archive_facts(db: Session, batch: str) -> int:
    _require_reference(db)
    params = {"batch": batch}
    _log_data_gaps(db, _ARCHIVE_SOURCE, params)
    result = db.execute(
        text(_insert_sql(_ARCHIVE_SOURCE)),
        {**params, "source": SOURCE_ARCHIVE, "batch_value": batch, "fallback_family": FALLBACK_FAMILY_CODE},
    )
    return result.rowcount
