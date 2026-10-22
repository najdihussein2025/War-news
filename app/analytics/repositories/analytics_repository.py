"""Read-side queries for the Analytics page.

Aggregates read only ``analytics_incident_facts``, ``analytics_air_breach_facts``,
``admin_areas`` and ``action_families``. The only raw-table reads are the drill-down
(``incidents`` / ``incidents_archive`` rows behind a number) and the ingest-coverage
signal (``raw_messages``). Every query is parameterised; the few identifiers that are
interpolated come from fixed whitelists in this module, never from request input.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.analytics.constants import AIR_CONDITION_LABELS, AIR_LEVEL_CONDITIONS
from app.analytics.dtos.filters import Filters
from app.analytics.services.status_buckets import bucket_sql

INCIDENT_LEVEL_COL = {"mohafaza": "f.mohafaza_code", "caza": "f.caza_code", "village": "f.admin_village_code"}
INCIDENT_METRIC_EXPR = {
    "incidents": "SUM(f.incidents)",
    "deaths": "SUM(f.deaths_total)",
    "injuries": "SUM(f.injuries_total)",
    "casualties": "SUM(f.deaths_total + f.injuries_total)",
}
INCIDENT_CHILD_LEVEL = {"mohafaza": "caza", "caza": "village"}


def rows(db: Session, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(r._mapping) for r in db.execute(text(sql), params)]


def one(db: Session, sql: str, params: dict[str, Any]) -> dict[str, Any]:
    row = db.execute(text(sql), params).first()
    return dict(row._mapping) if row else {}


# --------------------------------------------------------------------------- where builders
def incident_where(
    flt: Filters, *, pending_only: bool = False, with_area: bool = True,
    date_from: date | None = None, date_to: date | None = None, include_air_family: bool = False,
) -> tuple[str, dict[str, Any]]:
    """WHERE clause over ``analytics_incident_facts f JOIN action_families af``.

    Air-violation reports are not incidents: their family is left out of every incident
    number (KPIs, map, rankings, matrix, timeline), the same rule the matrix always used.
    Only the review queue (``include_air_family``) still sees them.
    """
    clauses = ["f.event_date BETWEEN :d_from AND :d_to"]
    params: dict[str, Any] = {"d_from": date_from or flt.date_from, "d_to": date_to or flt.date_to}
    if not include_air_family:
        clauses.append("NOT af.is_air_violation")
    if pending_only:
        clauses.append("f.bucket = 'pending'")
    elif not flt.include_pending:
        clauses.append("f.bucket = 'counted'")
    if flt.family:
        clauses.append("af.code = ANY(:families)")
        params["families"] = list(flt.family)
    if flt.condition_id:
        clauses.append("f.condition_id = ANY(:conds)")
        params["conds"] = list(flt.condition_id)
    if with_area and flt.area_code:
        clauses.append(f"{INCIDENT_LEVEL_COL[flt.area_level]} = :area")
        params["area"] = flt.area_code
    return " AND ".join(clauses), params


def air_where(
    flt: Filters, *, conditions: frozenset[int] | None = None, with_area: bool = True,
    date_from: date | None = None, date_to: date | None = None,
) -> tuple[str, dict[str, Any]]:
    """WHERE clause over ``analytics_air_breach_facts a JOIN action_families af``."""
    clauses = ["a.breach_date BETWEEN :d_from AND :d_to"]
    params: dict[str, Any] = {"d_from": date_from or flt.date_from, "d_to": date_to or flt.date_to}
    if flt.family:
        clauses.append("af.code = ANY(:families)")
        params["families"] = list(flt.family)
    allowed = conditions
    if flt.condition_id:
        wanted = set(flt.condition_id)
        allowed = frozenset(wanted & allowed) if allowed is not None else frozenset(wanted)
    if allowed is not None:
        clauses.append("a.condition_id = ANY(:air_conds)")
        params["air_conds"] = sorted(allowed)
    if with_area and flt.area_code:
        if flt.area_level == "mohafaza":
            clauses.append("a.unit_level <> 'unknown' AND a.mohafaza_code = :area")
        elif flt.area_level == "caza":
            clauses.append("a.unit_level IN ('caza', 'village') AND a.caza_code = :area")
        else:
            clauses.append("a.unit_level = 'village' AND a.area_code = :area")
        params["area"] = flt.area_code
    return " AND ".join(clauses), params


def air_level_columns(level: str) -> tuple[str, str]:
    """(code column, extra predicate) for rolling breaches up to ``level``."""
    if level == "mohafaza":
        return "a.mohafaza_code", "a.unit_level <> 'unknown'"
    if level == "caza":
        return "a.caza_code", "a.unit_level IN ('caza', 'village')"
    return "a.area_code", "a.unit_level = 'village'"


def unsupported_air_levels() -> dict[str, list[int]]:
    every = AIR_LEVEL_CONDITIONS["mohafaza"]
    return {level: sorted(every - allowed) for level, allowed in AIR_LEVEL_CONDITIONS.items() if every - allowed}


FROM_INCIDENTS = "FROM analytics_incident_facts f JOIN action_families af ON af.id = f.family_id"
FROM_AIR = "FROM analytics_air_breach_facts a JOIN action_families af ON af.id = a.family_id"


# --------------------------------------------------------------------------- meta
def meta(db: Session) -> dict[str, Any]:
    bounds = one(db, """
        SELECT min(event_date) AS first_date, max(event_date) AS last_date,
               min(event_date) FILTER (WHERE source = 'live') AS live_first,
               max(event_date) FILTER (WHERE source = 'archive') AS archive_cutoff,
               max(refreshed_at) AS incidents_refreshed
        FROM analytics_incident_facts""", {})
    air = one(db, "SELECT min(breach_date) AS first_date, max(breach_date) AS last_date, "
                  "max(refreshed_at) AS refreshed FROM analytics_air_breach_facts", {})
    all_time = Filters(date_from=date(1900, 1, 1), date_to=date(2999, 12, 31))
    pending_total = pending_review_count(db, all_time)
    pending_live = one(db, "SELECT coalesce(sum(incidents), 0) AS n FROM analytics_incident_facts "
                           "WHERE bucket = 'pending' AND source = 'live'", {})["n"]
    counts = {r["level"]: r["n"] for r in rows(db, "SELECT level, count(*) AS n FROM admin_areas GROUP BY level", {})}
    families = rows(db, """
        SELECT code, name_en, name_ar, sort_order, is_air_violation, counts_in_headline
        FROM action_families ORDER BY sort_order, code""", {})
    batches = rows(db, "SELECT archive_batch, min(archived_at) AS archived_at, count(*) AS incidents "
                       "FROM incidents_archive GROUP BY archive_batch ORDER BY 2", {})
    queue = one(db, "SELECT count(*) AS n FROM analytics_dirty_dates", {})
    refreshed = [t for t in (bounds.get("incidents_refreshed"), air.get("refreshed")) if t]
    return {
        "incident_data": {"first_date": bounds.get("first_date"), "last_date": bounds.get("last_date")},
        "air_data": {"first_date": air.get("first_date"), "last_date": air.get("last_date")},
        "archive": {"cutoff_date": bounds.get("archive_cutoff"), "batches": batches},
        "families": families,
        "area_counts": counts,
        "last_refresh": max(refreshed) if refreshed else None,
        "refresh_queue": queue.get("n", 0),
        # All-time count, for the footer only. The filter chip shows kpis.pending_review
        # (same function, current filters) so it always equals the KPI card.
        "pending_review": {"incidents": pending_total, "live": int(pending_live)},
        "air_conditions": {str(k): v for k, v in AIR_CONDITION_LABELS.items()},
        "air_level_conditions": {k: sorted(v) for k, v in AIR_LEVEL_CONDITIONS.items()},
    }


# --------------------------------------------------------------------------- map
def map_incident_values(db: Session, flt: Filters) -> list[dict[str, Any]]:
    where, params = incident_where(flt)
    col = INCIDENT_LEVEL_COL[flt.level]
    return rows(db, f"""
        SELECT {col} AS code, {INCIDENT_METRIC_EXPR[flt.metric]} AS value
        {FROM_INCIDENTS} WHERE {where} AND {col} IS NOT NULL
        GROUP BY {col} HAVING {INCIDENT_METRIC_EXPR[flt.metric]} > 0 ORDER BY {col}""", params)


def map_air_values(db: Session, flt: Filters, conditions: frozenset[int]) -> list[dict[str, Any]]:
    where, params = air_where(flt, conditions=conditions)
    col, pred = air_level_columns(flt.level)
    return rows(db, f"""
        SELECT {col} AS code, SUM(a.breaches) AS value
        {FROM_AIR} WHERE {where} AND {pred} AND {col} IS NOT NULL
        GROUP BY {col} HAVING SUM(a.breaches) > 0 ORDER BY {col}""", params)


def incident_breakdown_by_area(db: Session, flt: Filters, codes: list[str]) -> dict[str, dict[str, int]]:
    """Per-area family breakdown for map tooltips."""
    where, params = incident_where(flt)
    col = INCIDENT_LEVEL_COL[flt.level]
    result: dict[str, dict[str, int]] = {}
    for r in rows(db, f"""
        SELECT {col} AS code, af.code AS family, {INCIDENT_METRIC_EXPR[flt.metric]} AS value
        {FROM_INCIDENTS} WHERE {where} AND {col} = ANY(:codes) GROUP BY {col}, af.code""",
            {**params, "codes": codes}):
        result.setdefault(r["code"], {})[r["family"]] = int(r["value"])
    return result


# --------------------------------------------------------------------------- kpis
def incident_totals(db: Session, flt: Filters, *, pending_only: bool = False) -> dict[str, Any]:
    where, params = incident_where(flt, pending_only=pending_only)
    return one(db, f"""
        SELECT coalesce(SUM(f.incidents), 0) AS incidents,
               coalesce(SUM(f.deaths_total), 0) AS deaths,
               coalesce(SUM(f.deaths_male), 0) AS deaths_male, coalesce(SUM(f.deaths_female), 0) AS deaths_female,
               coalesce(SUM(f.deaths_children), 0) AS deaths_children,
               coalesce(SUM(f.deaths_unspecified), 0) AS deaths_unspecified,
               coalesce(SUM(f.injuries_total), 0) AS injuries,
               coalesce(SUM(f.injuries_male), 0) AS injuries_male, coalesce(SUM(f.injuries_female), 0) AS injuries_female,
               coalesce(SUM(f.injuries_children), 0) AS injuries_children,
               coalesce(SUM(f.injuries_unspecified), 0) AS injuries_unspecified,
               coalesce(SUM(f.aggregate_only_incidents), 0) AS aggregate_only_incidents,
               count(DISTINCT f.village_id) FILTER (WHERE f.incidents > 0) AS villages_affected,
               count(DISTINCT f.caza_code) FILTER (WHERE f.incidents > 0) AS cazas_affected
        {FROM_INCIDENTS} WHERE {where}""", params)


def pending_review_count(db: Session, flt: Filters) -> int:
    """The one "pending review" number (filter chip, KPI card, area panel, meta, export).

    Pending = not deleted, not rejected, and either ``needs_verification`` or an action in
    a family that does not count in the headline (the unclassified family). It is the
    ``pending`` bucket of ``status_buckets``; the date, family, condition and area
    filters apply, the include-pending toggle does not.
    """
    where, params = incident_where(flt, pending_only=True, include_air_family=True)
    return int(one(db, f"SELECT coalesce(SUM(f.incidents), 0) AS n {FROM_INCIDENTS} WHERE {where}", params)["n"])


def casualty_completeness(db: Session, flt: Filters) -> dict[str, Any]:
    """How many incidents in the filtered set state a toll, or mention one without a number."""
    where, params = incident_where(flt)
    row = one(db, f"""SELECT coalesce(SUM(f.incidents), 0) AS incidents, coalesce(SUM(f.casualty_known), 0) AS known,
                             coalesce(SUM(f.casualty_explicit), 0) AS explicit,
                             coalesce(SUM(f.casualty_count_missing), 0) AS missing
                      {FROM_INCIDENTS} WHERE {where}""", params)
    incidents, known = int(row["incidents"]), int(row["known"])
    return {"incidents": incidents, "with_status": known,
            "pct": round(known / incidents * 100, 1) if incidents else None,
            "with_casualties": int(row["explicit"]), "count_missing": int(row["missing"])}


def bucket_totals(db: Session, flt: Filters) -> dict[str, int]:
    """Counted and pending incidents under the same filters (the "% verified" KPI)."""
    where, params = incident_where(flt.model_copy(update={"include_pending": True}))
    row = one(db, f"""SELECT coalesce(SUM(f.incidents) FILTER (WHERE f.bucket = 'counted'), 0) AS counted,
                             coalesce(SUM(f.incidents) FILTER (WHERE f.bucket = 'pending'), 0) AS pending
                      {FROM_INCIDENTS} WHERE {where}""", params)
    return {"counted": int(row["counted"]), "pending": int(row["pending"])}


def incident_fact_bounds(db: Session) -> dict[str, Any]:
    """Last day with any incident fact (the end of the data, whatever the filters) and the last refresh."""
    return one(db, "SELECT max(event_date) AS last_date, max(refreshed_at) AS refreshed_at "
                   "FROM analytics_incident_facts", {})


def queued_dates(db: Session, kind: str | None = None) -> list[dict[str, Any]]:
    sql = "SELECT kind, event_date, marked_at FROM analytics_dirty_dates"
    if kind:
        sql += " WHERE kind = :kind"
    return rows(db, sql + " ORDER BY event_date, kind", {"kind": kind})


def air_totals_by_condition(db: Session, flt: Filters) -> dict[int, int]:
    where, params = air_where(flt)
    return {int(r["condition_id"]): int(r["n"]) for r in rows(db, f"""
        SELECT a.condition_id, SUM(a.breaches) AS n {FROM_AIR} WHERE {where} GROUP BY a.condition_id""", params)}


def daily_incident_series(db: Session, flt: Filters, metric: str) -> list[dict[str, Any]]:
    where, params = incident_where(flt)
    return rows(db, f"""
        SELECT f.event_date AS date, {INCIDENT_METRIC_EXPR[metric]} AS value
        {FROM_INCIDENTS} WHERE {where} GROUP BY f.event_date ORDER BY f.event_date""", params)


def daily_air_series(db: Session, flt: Filters) -> list[dict[str, Any]]:
    where, params = air_where(flt)
    return rows(db, f"""
        SELECT a.breach_date AS date, SUM(a.breaches) AS value {FROM_AIR} WHERE {where}
        GROUP BY a.breach_date ORDER BY a.breach_date""", params)


# --------------------------------------------------------------------------- timeline
def timeline_incident_series(db: Session, flt: Filters, grain: str) -> list[dict[str, Any]]:
    where, params = incident_where(flt)
    return rows(db, f"""
        SELECT date_trunc(:grain, f.event_date)::date AS bucket, af.code AS key,
               {INCIDENT_METRIC_EXPR[flt.metric]} AS value
        {FROM_INCIDENTS} WHERE {where} GROUP BY 1, af.code ORDER BY 1, af.code""", {**params, "grain": grain})


def timeline_air_series(db: Session, flt: Filters, grain: str) -> list[dict[str, Any]]:
    where, params = air_where(flt)
    return rows(db, f"""
        SELECT date_trunc(:grain, a.breach_date)::date AS bucket, a.condition_id AS key, SUM(a.breaches) AS value
        {FROM_AIR} WHERE {where} GROUP BY 1, a.condition_id ORDER BY 1, a.condition_id""", {**params, "grain": grain})


COVERAGE_BASELINE_DAYS = 28


def coverage_days(db: Session, date_from: date, date_to: date, low_ratio: float) -> list[dict[str, Any]]:
    """Daily ingestion coverage from raw_messages (Beirut days), per source.

    status: ``none`` (no message at all), ``low`` (fewer than ``low_ratio`` x the median
    of the non-zero daily totals in the previous 28 days), ``ok``, or ``unknown`` for days
    before the first message ever ingested (nothing was collected yet, so no signal).
    """
    start = date.fromordinal(date_from.toordinal() - COVERAGE_BASELINE_DAYS)
    first = one(db, "SELECT min((message_datetime AT TIME ZONE 'Asia/Beirut')::date) AS d FROM raw_messages", {})
    first_day = first.get("d")
    counts = rows(db, """
        SELECT (r.message_datetime AT TIME ZONE 'Asia/Beirut')::date AS day,
               coalesce(s.name, r.source_name, 'unknown') AS source, count(*) AS n
        FROM raw_messages r LEFT JOIN sources s ON s.id = r.source_id
        WHERE r.message_datetime >= CAST(:a AS date) - interval '3 hours'
          AND r.message_datetime < CAST(:b AS date) + interval '1 day'
        GROUP BY 1, 2""", {"a": start, "b": date_to})
    totals: dict[date, int] = {}
    by_source: dict[date, dict[str, int]] = {}
    for r in counts:
        if r["day"] < start or r["day"] > date_to:
            continue
        totals[r["day"]] = totals.get(r["day"], 0) + int(r["n"])
        by_source.setdefault(r["day"], {})[r["source"]] = int(r["n"])
    out: list[dict[str, Any]] = []
    day = date_from
    while day <= date_to:
        window = sorted(v for d, v in totals.items()
                        if 0 < (day - d).days <= COVERAGE_BASELINE_DAYS and v > 0)
        baseline = window[len(window) // 2] if window else None
        total = totals.get(day, 0)
        if first_day is None or day < first_day:
            status = "unknown"
        elif total == 0:
            status = "none"
        elif baseline and total < low_ratio * baseline:
            status = "low"
        else:
            status = "ok"
        out.append({"date": day, "messages": total, "baseline": baseline, "status": status,
                    "sources": by_source.get(day, {})})
        day = date.fromordinal(day.toordinal() + 1)
    return out


def geo_anomalies(db: Session, flt: Filters, min_incidents: int,
                  zone_mohafazat: frozenset[str], zone_cazas: frozenset[str]) -> list[dict[str, Any]]:
    """Villages outside the conflict zone with more than ``min_incidents`` (counted + pending)."""
    where, params = incident_where(flt.model_copy(update={"include_pending": True}), include_air_family=True)
    return rows(db, f"""
        WITH v AS (
            SELECT f.admin_village_code AS code, af.code AS family, SUM(f.incidents) AS n,
                   MIN(f.event_date) AS first_date, MAX(f.event_date) AS last_date
            {FROM_INCIDENTS} WHERE {where} AND f.admin_village_code IS NOT NULL
              AND NOT (f.mohafaza_code = ANY(:zone_moh)) AND NOT (f.caza_code = ANY(:zone_caza))
            GROUP BY 1, 2
        ), t AS (
            SELECT code, SUM(n) AS incidents, MIN(first_date) AS first_date, MAX(last_date) AS last_date
            FROM v GROUP BY code HAVING SUM(n) > :min_n
        ), dom AS (SELECT DISTINCT ON (code) code, family FROM v ORDER BY code, n DESC, family)
        SELECT t.code, a.name_en, a.name_ar, c.name_en AS caza_en, m.name_en AS mohafaza_en,
               t.incidents, t.first_date, t.last_date, dom.family AS dominant_family
        FROM t JOIN dom ON dom.code = t.code JOIN admin_areas a ON a.code = t.code
        LEFT JOIN admin_areas c ON c.code = a.caza_code LEFT JOIN admin_areas m ON m.code = a.mohafaza_code
        ORDER BY t.incidents DESC, a.name_en""",
        {**params, "min_n": min_incidents, "zone_moh": sorted(zone_mohafazat), "zone_caza": sorted(zone_cazas)})


# --------------------------------------------------------------------------- rankings
def rank_incident_areas(db: Session, flt: Filters, level: str, limit: int) -> list[dict[str, Any]]:
    where, params = incident_where(flt)
    col = INCIDENT_LEVEL_COL[level]
    metric = flt.metric if flt.metric != "breaches" else "incidents"
    order = {"incidents": "t.incidents", "deaths": "t.deaths", "injuries": "t.injuries",
             "casualties": "(t.deaths + t.injuries)"}[metric]
    return rows(db, f"""
        WITH base AS (
            SELECT {col} AS code, af.code AS family, SUM(f.incidents) AS inc, SUM(f.deaths_total) AS d,
                   SUM(f.injuries_total) AS i,
                   MIN(f.event_date) FILTER (WHERE f.incidents > 0) AS first_date,
                   MAX(f.event_date) FILTER (WHERE f.incidents > 0) AS last_date
            {FROM_INCIDENTS} WHERE {where} AND {col} IS NOT NULL GROUP BY {col}, af.code
        ), t AS (
            SELECT code, SUM(inc) AS incidents, SUM(d) AS deaths, SUM(i) AS injuries,
                   MIN(first_date) AS first_date, MAX(last_date) AS last_date FROM base GROUP BY code
        ), dom AS (
            SELECT DISTINCT ON (code) code, family FROM base ORDER BY code, inc DESC, family
        ), days AS (
            SELECT {col} AS code, COUNT(DISTINCT f.event_date) FILTER (WHERE f.incidents > 0) AS days_hit,
                   coalesce({INCIDENT_METRIC_EXPR[metric]} FILTER (WHERE f.event_date > :last7_after), 0) AS last_7d
            {FROM_INCIDENTS} WHERE {where} AND {col} IS NOT NULL GROUP BY {col}
        )
        SELECT t.code, a.level, a.name_en, a.name_ar, p.name_en AS parent_name_en, p.name_ar AS parent_name_ar,
               t.incidents, t.deaths, t.injuries, (t.deaths + t.injuries) AS casualties,
               t.first_date, t.last_date, dom.family AS dominant_family, days.days_hit, days.last_7d
        FROM t JOIN dom ON dom.code = t.code JOIN days ON days.code = t.code JOIN admin_areas a ON a.code = t.code
        LEFT JOIN admin_areas p ON p.code = a.parent_code
        WHERE {order} > 0
        ORDER BY {order} DESC, a.name_en, t.code LIMIT :limit""",
        {**params, "limit": limit, "last7_after": flt.date_to - timedelta(days=7)})


def rank_air_areas(db: Session, flt: Filters, level: str, limit: int) -> list[dict[str, Any]]:
    sub = flt.model_copy(update={"level": level})
    conditions = AIR_LEVEL_CONDITIONS[level]
    where, params = air_where(sub, conditions=conditions)
    col, pred = air_level_columns(level)
    return rows(db, f"""
        WITH base AS (
            SELECT {col} AS code, a.condition_id, SUM(a.breaches) AS n,
                   MIN(a.breach_date) AS first_date, MAX(a.breach_date) AS last_date
            {FROM_AIR} WHERE {where} AND {pred} AND {col} IS NOT NULL GROUP BY {col}, a.condition_id
        ), t AS (
            SELECT code, SUM(n) AS breaches, MIN(first_date) AS first_date, MAX(last_date) AS last_date
            FROM base GROUP BY code
        ), dom AS (SELECT DISTINCT ON (code) code, condition_id FROM base ORDER BY code, n DESC, condition_id
        ), days AS (
            SELECT {col} AS code, COUNT(DISTINCT a.breach_date) FILTER (WHERE a.breaches > 0) AS days_hit,
                   coalesce(SUM(a.breaches) FILTER (WHERE a.breach_date > :last7_after), 0) AS last_7d
            {FROM_AIR} WHERE {where} AND {pred} AND {col} IS NOT NULL GROUP BY {col}
        )
        SELECT t.code, a.level, a.name_en, a.name_ar, p.name_en AS parent_name_en, p.name_ar AS parent_name_ar,
               t.breaches, t.first_date, t.last_date, dom.condition_id AS dominant_condition,
               days.days_hit, days.last_7d
        FROM t JOIN dom ON dom.code = t.code JOIN days ON days.code = t.code JOIN admin_areas a ON a.code = t.code
        LEFT JOIN admin_areas p ON p.code = a.parent_code
        ORDER BY t.breaches DESC, a.name_en, t.code LIMIT :limit""",
        {**params, "limit": limit, "last7_after": flt.date_to - timedelta(days=7)})


# --------------------------------------------------------------------------- peaks
def peak_periods(db: Session, flt: Filters, unit: str, metric: str) -> dict[str, Any] | None:
    if metric == "breaches":
        where, params = air_where(flt)
        row = one(db, f"""
            SELECT date_trunc(:unit, a.breach_date)::date AS start, SUM(a.breaches) AS value
            {FROM_AIR} WHERE {where} GROUP BY 1 HAVING SUM(a.breaches) > 0
            ORDER BY value DESC, start DESC LIMIT 1""", {**params, "unit": unit})
    else:
        where, params = incident_where(flt)
        row = one(db, f"""
            SELECT date_trunc(:unit, f.event_date)::date AS start, {INCIDENT_METRIC_EXPR[metric]} AS value
            {FROM_INCIDENTS} WHERE {where} GROUP BY 1 HAVING {INCIDENT_METRIC_EXPR[metric]} > 0
            ORDER BY value DESC, start DESC LIMIT 1""", {**params, "unit": unit})
    return row or None


def top_cazas_for_period(db: Session, flt: Filters, start: date, unit: str, metric: str) -> list[dict[str, Any]]:
    end = date.fromordinal(start.toordinal() + (6 if unit == "week" else 0))
    if unit == "week":
        end = min(end, flt.date_to)
    start = max(start, flt.date_from)
    if metric == "breaches":
        where, params = air_where(flt, date_from=start, date_to=end)
        return rows(db, f"""
            SELECT a.caza_code AS code, ar.name_en, ar.name_ar, SUM(a.breaches) AS value
            {FROM_AIR} JOIN admin_areas ar ON ar.code = a.caza_code
            WHERE {where} AND a.unit_level IN ('caza', 'village') GROUP BY a.caza_code, ar.name_en, ar.name_ar
            ORDER BY value DESC, code LIMIT 3""", params)
    where, params = incident_where(flt, date_from=start, date_to=end)
    return rows(db, f"""
        SELECT f.caza_code AS code, ar.name_en, ar.name_ar, {INCIDENT_METRIC_EXPR[metric]} AS value
        {FROM_INCIDENTS} JOIN admin_areas ar ON ar.code = f.caza_code
        WHERE {where} GROUP BY f.caza_code, ar.name_en, ar.name_ar
        HAVING {INCIDENT_METRIC_EXPR[metric]} > 0 ORDER BY value DESC, code LIMIT 3""", params)


# --------------------------------------------------------------------------- matrix
def matrix_cells(db: Session, flt: Filters, by: str = "caza") -> list[dict[str, Any]]:
    """Area x family cells; ``by`` is ``caza`` or ``mohafaza`` (the row key is still called ``caza``)."""
    where, params = incident_where(flt)
    col = INCIDENT_LEVEL_COL[by]
    return rows(db, f"""
        SELECT {col} AS caza, af.code AS family, {INCIDENT_METRIC_EXPR[flt.metric]} AS value
        {FROM_INCIDENTS} WHERE {where} AND {col} IS NOT NULL GROUP BY {col}, af.code""", params)


def matrix_unplaced(db: Session, flt: Filters, by: str = "caza") -> int:
    """Incidents in the filtered set whose village has no HDX code (no row in the matrix)."""
    where, params = incident_where(flt)
    col = INCIDENT_LEVEL_COL[by]
    return int(one(db, f"""SELECT coalesce({INCIDENT_METRIC_EXPR[flt.metric]}, 0) AS n
                           {FROM_INCIDENTS} WHERE {where} AND {col} IS NULL""", params)["n"])


def matrix_air_cells(db: Session, flt: Filters) -> list[dict[str, Any]]:
    where, params = air_where(flt)
    return rows(db, f"""
        SELECT a.caza_code AS caza, 'air_violations' AS family, SUM(a.breaches) AS value
        {FROM_AIR} WHERE {where} AND a.unit_level IN ('caza', 'village') AND a.caza_code IS NOT NULL
        GROUP BY a.caza_code""", params)


def caza_rows(db: Session, level: str = "caza") -> list[dict[str, Any]]:
    return rows(db, """SELECT a.code, a.name_en, a.name_ar, a.mohafaza_code FROM admin_areas a
                       WHERE level = :level ORDER BY a.name_en""", {"level": level})


# --------------------------------------------------------------------------- area profile
def area_info(db: Session, code: str) -> dict[str, Any] | None:
    return one(db, """
        SELECT a.code, a.level, a.name_en, a.name_ar, a.parent_code, a.area_km2, a.center_lat, a.center_lon,
               a.is_disputed, p.name_en AS parent_name_en, p.name_ar AS parent_name_ar
        FROM admin_areas a LEFT JOIN admin_areas p ON p.code = a.parent_code WHERE a.code = :c""", {"c": code}) or None


def family_breakdown(db: Session, flt: Filters) -> list[dict[str, Any]]:
    where, params = incident_where(flt)
    return rows(db, f"""
        SELECT af.code, af.name_en, af.name_ar, SUM(f.incidents) AS incidents,
               SUM(f.deaths_total) AS deaths, SUM(f.injuries_total) AS injuries
        {FROM_INCIDENTS} WHERE {where} GROUP BY af.code, af.name_en, af.name_ar, af.sort_order
        HAVING SUM(f.incidents) > 0 ORDER BY SUM(f.incidents) DESC, af.sort_order""", params)


def condition_breakdown(db: Session, flt: Filters) -> list[dict[str, Any]]:
    where, params = incident_where(flt)
    return rows(db, f"""
        SELECT c.id AS condition_id, c.action_en, c.action_ar, af.code AS family, SUM(f.incidents) AS incidents,
               SUM(f.deaths_total) AS deaths, SUM(f.injuries_total) AS injuries
        {FROM_INCIDENTS} JOIN conditions c ON c.id = f.condition_id
        WHERE {where} GROUP BY c.id, c.action_en, c.action_ar, af.code
        HAVING SUM(f.incidents) > 0 ORDER BY SUM(f.incidents) DESC, c.id""", params)


def first_last_hit(db: Session, flt: Filters) -> dict[str, Any]:
    where, params = incident_where(flt, date_from=date(2000, 1, 1), date_to=date(2100, 1, 1))
    return one(db, f"""
        SELECT min(f.event_date) FILTER (WHERE f.incidents > 0) AS first_date,
               max(f.event_date) FILTER (WHERE f.incidents > 0) AS last_date {FROM_INCIDENTS} WHERE {where}""", params)


# --------------------------------------------------------------------------- raw incident rows
# The fact tables cover every number; these few views need a raw-row column the facts do not
# keep (the incident list, channel, review reason, quality flags). raw_where() applies the
# same filters and the same bucket rule, so their totals match the fact-based numbers.
_DRILL_CTE = """
WITH src AS (
    SELECT i.id, i.event_date, i.event_time, i.village_id, i.condition_id, i.verification_status, i.is_deleted,
           i.total_deaths, i.total_injuries, i.khabar, i.raw_message_id, i.verification_reason, i.quality_flags,
           'live' AS source, NULL::text AS archive_batch
    FROM incidents i WHERE NOT EXISTS (SELECT 1 FROM incidents_archive x WHERE x.id = i.id)
    UNION ALL
    SELECT a.id, a.event_date, a.event_time, a.village_id, a.condition_id, a.verification_status, a.is_deleted,
           a.total_deaths, a.total_injuries, a.khabar, a.raw_message_id, a.verification_reason, a.quality_flags,
           'archive', a.archive_batch
    FROM incidents_archive a
), joined AS (
    SELECT s.*, v.ref_name_en AS village_en, v.ref_name_ar AS village_ar, aa.code AS admin_village_code,
           aa.caza_code, aa.mohafaza_code, c.action_en, c.action_ar,
           af.code AS family, af.is_air_violation AS is_air, {bucket} AS bucket
    FROM src s
    JOIN conditions c ON c.id = s.condition_id
    LEFT JOIN condition_families cf ON cf.condition_id = s.condition_id
    LEFT JOIN action_families uf ON uf.code = 'unclassified'
    JOIN action_families af ON af.id = COALESCE(cf.family_id, uf.id)
    LEFT JOIN villages v ON v.id = s.village_id
    LEFT JOIN admin_areas aa ON aa.code = v.admin_area_code
)
"""
# quality_flags is stored either as a list or as {"quality_flags": [...]}.
QUALITY_FLAGS_LIST = ("CASE jsonb_typeof(j.quality_flags) WHEN 'array' THEN j.quality_flags "
                      "WHEN 'object' THEN coalesce(j.quality_flags -> 'quality_flags', '[]'::jsonb) "
                      "ELSE '[]'::jsonb END")


def raw_where(
    flt: Filters, *, pending_only: bool = False, include_air_family: bool = False, metric_rows: bool = True,
) -> tuple[str, str, dict[str, Any]]:
    """(cte, WHERE over ``joined j``, params) with the same rules as :func:`incident_where`."""
    bucket = bucket_sql("s.verification_status", "s.is_deleted", "af.counts_in_headline")
    clauses = ["j.bucket IS NOT NULL", "j.event_date BETWEEN :d_from AND :d_to"]
    params: dict[str, Any] = {"d_from": flt.date_from, "d_to": flt.date_to}
    if pending_only:
        clauses.append("j.bucket = 'pending'")
    elif not flt.include_pending:
        clauses.append("j.bucket = 'counted'")
    if not include_air_family:
        clauses.append("NOT j.is_air")
    if flt.family:
        clauses.append("j.family = ANY(:families)")
        params["families"] = list(flt.family)
    if flt.condition_id:
        clauses.append("j.condition_id = ANY(:conds)")
        params["conds"] = list(flt.condition_id)
    if flt.area_code:
        column = {"mohafaza": "j.mohafaza_code", "caza": "j.caza_code", "village": "j.admin_village_code"}[flt.area_level]
        clauses.append(f"{column} = :area")
        params["area"] = flt.area_code
    if metric_rows and flt.metric == "deaths":
        clauses.append("coalesce(j.total_deaths, 0) > 0")
    elif metric_rows and flt.metric == "injuries":
        clauses.append("coalesce(j.total_injuries, 0) > 0")
    elif metric_rows and flt.metric == "casualties":
        clauses.append("coalesce(j.total_deaths, 0) + coalesce(j.total_injuries, 0) > 0")
    return _DRILL_CTE.format(bucket=bucket), " AND ".join(clauses), params


def drilldown(db: Session, flt: Filters, *, offset: int, limit: int) -> tuple[int, list[dict[str, Any]]]:
    cte, where, params = raw_where(flt)
    total = one(db, f"{cte} SELECT count(*) AS n FROM joined j WHERE {where}", params)["n"]
    data = rows(db, f"""{cte}
        SELECT j.id, j.event_date, j.event_time, j.village_en, j.village_ar, j.action_en, j.action_ar,
               j.family, j.verification_status, j.bucket, j.source,
               coalesce(j.total_deaths, 0) AS deaths, coalesce(j.total_injuries, 0) AS injuries,
               left(j.khabar, 200) AS khabar_excerpt, j.admin_village_code, j.caza_code
        FROM joined j WHERE {where}
        ORDER BY j.event_date DESC, j.event_time DESC NULLS LAST, j.id
        OFFSET :offset LIMIT :limit""", {**params, "offset": offset, "limit": limit})
    return int(total), data


def casualty_incidents(db: Session, flt: Filters, limit: int) -> tuple[int, list[dict[str, Any]]]:
    """Incidents with a stated toll (deaths or injuries > 0), newest first, with their caza."""
    cte, where, params = raw_where(flt.model_copy(update={"metric": "casualties"}))
    total = one(db, f"{cte} SELECT count(*) AS n FROM joined j WHERE {where}", params)["n"]
    data = rows(db, f"""{cte}
        SELECT j.id, j.event_date, j.village_en, j.village_ar, ca.name_en AS caza_en, ca.name_ar AS caza_ar,
               j.action_en, j.family, j.verification_status, j.bucket,
               coalesce(j.total_deaths, 0) AS deaths, coalesce(j.total_injuries, 0) AS injuries
        FROM joined j LEFT JOIN admin_areas ca ON ca.code = j.caza_code
        WHERE {where} ORDER BY j.event_date DESC, j.event_time DESC NULLS LAST, j.id LIMIT :limit""",
        {**params, "limit": limit})
    return int(total), data


def channel_breakdown(db: Session, flt: Filters, limit: int = 30) -> list[dict[str, Any]]:
    """Incidents per originating channel (``raw_messages.source_name``); NULL = no raw message."""
    cte, where, params = raw_where(flt)
    return rows(db, f"""{cte}
        SELECT coalesce(r.source_name, 'unknown') AS channel, max(r.source_platform) AS platform,
               count(*) AS incidents,
               coalesce(sum(j.total_deaths), 0) AS deaths, coalesce(sum(j.total_injuries), 0) AS injuries
        FROM joined j LEFT JOIN raw_messages r ON r.id = j.raw_message_id
        WHERE {where} GROUP BY 1 ORDER BY incidents DESC, channel LIMIT :limit""", {**params, "limit": limit})


def review_reason_counts(db: Session, flt: Filters, category_sql: str) -> list[dict[str, Any]]:
    """Pending incidents by review-reason category; ``category_sql`` is a CASE over j.verification_reason."""
    cte, where, params = raw_where(flt, pending_only=True, include_air_family=True, metric_rows=False)
    return rows(db, f"""{cte}
        SELECT {category_sql} AS category, count(*) AS incidents
        FROM joined j WHERE {where} GROUP BY 1 ORDER BY incidents DESC, category""", params)


def village_match_counts(db: Session, flt: Filters) -> dict[str, int]:
    """Counted + pending incidents with no matched village, or with a low-confidence match flag."""
    cte, where, params = raw_where(flt.model_copy(update={"include_pending": True}), include_air_family=True,
                                   metric_rows=False)
    row = one(db, f"""{cte}
        SELECT count(*) AS incidents,
               count(*) FILTER (WHERE j.village_id IS NULL) AS no_village,
               count(*) FILTER (WHERE j.village_id IS NOT NULL AND j.admin_village_code IS NULL) AS no_area_code,
               count(*) FILTER (WHERE ({QUALITY_FLAGS_LIST}) @> '[{{"flag": "low_confidence_village"}}]'::jsonb)
                   AS low_confidence_village,
               count(*) FILTER (WHERE ({QUALITY_FLAGS_LIST}) @> '[{{"flag": "unresolved_condition"}}]'::jsonb)
                   AS unresolved_condition
        FROM joined j WHERE {where}""", params)
    return {k: int(v) for k, v in row.items()}


# --------------------------------------------------------------------------- tab aggregates (facts)
def daily_pending_series(db: Session, flt: Filters) -> list[dict[str, Any]]:
    where, params = incident_where(flt, pending_only=True, include_air_family=True)
    return rows(db, f"""SELECT f.event_date AS date, SUM(f.incidents) AS value {FROM_INCIDENTS}
                        WHERE {where} GROUP BY 1 ORDER BY 1""", params)


def daily_affected_series(db: Session, flt: Filters) -> list[dict[str, Any]]:
    """Villages and cazas with at least one incident, per day."""
    where, params = incident_where(flt)
    return rows(db, f"""
        SELECT f.event_date AS date,
               count(DISTINCT f.village_id) FILTER (WHERE f.incidents > 0) AS villages,
               count(DISTINCT f.caza_code) FILTER (WHERE f.incidents > 0) AS cazas
        {FROM_INCIDENTS} WHERE {where} GROUP BY 1 ORDER BY 1""", params)


def casualty_series(db: Session, flt: Filters, grain: str) -> list[dict[str, Any]]:
    where, params = incident_where(flt)
    return rows(db, f"""
        SELECT date_trunc(:grain, f.event_date)::date AS bucket, SUM(f.deaths_total) AS deaths,
               SUM(f.injuries_total) AS injuries
        {FROM_INCIDENTS} WHERE {where} GROUP BY 1 ORDER BY 1""", {**params, "grain": grain})


def casualties_by_area(db: Session, flt: Filters, level: str) -> list[dict[str, Any]]:
    where, params = incident_where(flt)
    col = INCIDENT_LEVEL_COL[level]
    return rows(db, f"""
        WITH t AS (
            SELECT {col} AS code, SUM(f.deaths_total) AS deaths, SUM(f.injuries_total) AS injuries,
                   SUM(f.deaths_male) AS deaths_male, SUM(f.deaths_female) AS deaths_female,
                   SUM(f.deaths_children) AS deaths_children, SUM(f.injuries_male) AS injuries_male,
                   SUM(f.injuries_female) AS injuries_female, SUM(f.injuries_children) AS injuries_children
            {FROM_INCIDENTS} WHERE {where} AND {col} IS NOT NULL GROUP BY 1
        )
        SELECT t.*, a.name_en, a.name_ar FROM t JOIN admin_areas a ON a.code = t.code
        WHERE t.deaths + t.injuries > 0 ORDER BY t.deaths + t.injuries DESC, a.name_en""", params)


def area_period_comparison(db: Session, flt: Filters, level: str) -> list[dict[str, Any]]:
    """Metric per area in the period and in the previous equal-length period (one scan)."""
    prev = flt.previous_period()
    col = INCIDENT_LEVEL_COL[level]
    expr = INCIDENT_METRIC_EXPR[flt.metric if flt.metric != "breaches" else "incidents"]
    where, params = incident_where(flt, date_from=prev.date_from, date_to=flt.date_to)
    return rows(db, f"""
        WITH t AS (
            SELECT {col} AS code,
                   coalesce({expr} FILTER (WHERE f.event_date >= :cur_from), 0) AS current,
                   coalesce({expr} FILTER (WHERE f.event_date < :cur_from), 0) AS previous
            {FROM_INCIDENTS} WHERE {where} AND {col} IS NOT NULL GROUP BY 1
        )
        SELECT t.*, a.name_en, a.name_ar FROM t JOIN admin_areas a ON a.code = t.code
        WHERE t.current + t.previous > 0 ORDER BY t.current DESC, t.previous DESC, a.name_en""",
        {**params, "cur_from": flt.date_from})


def air_area_period_comparison(db: Session, flt: Filters, level: str) -> list[dict[str, Any]]:
    prev = flt.previous_period()
    col, pred = air_level_columns(level)
    where, params = air_where(flt, conditions=AIR_LEVEL_CONDITIONS[level], date_from=prev.date_from)
    return rows(db, f"""
        WITH t AS (
            SELECT {col} AS code,
                   coalesce(SUM(a.breaches) FILTER (WHERE a.breach_date >= :cur_from), 0) AS current,
                   coalesce(SUM(a.breaches) FILTER (WHERE a.breach_date < :cur_from), 0) AS previous
            {FROM_AIR} WHERE {where} AND {pred} AND {col} IS NOT NULL GROUP BY 1
        )
        SELECT t.*, ar.name_en, ar.name_ar FROM t JOIN admin_areas ar ON ar.code = t.code
        WHERE t.current + t.previous > 0 ORDER BY t.current DESC, t.previous DESC, ar.name_en""",
        {**params, "cur_from": flt.date_from})


def area_week_series(db: Session, flt: Filters, level: str, codes: list[str]) -> list[dict[str, Any]]:
    """Weekly metric per area for the ranking sparklines (only the listed areas)."""
    if not codes:
        return []
    if flt.metric == "breaches":
        col, pred = air_level_columns(level)
        where, params = air_where(flt, conditions=AIR_LEVEL_CONDITIONS[level])
        return rows(db, f"""
            SELECT {col} AS code, date_trunc('week', a.breach_date)::date AS bucket, SUM(a.breaches) AS value
            {FROM_AIR} WHERE {where} AND {pred} AND {col} = ANY(:codes) GROUP BY 1, 2 ORDER BY 1, 2""",
            {**params, "codes": codes})
    where, params = incident_where(flt)
    col = INCIDENT_LEVEL_COL[level]
    return rows(db, f"""
        SELECT {col} AS code, date_trunc('week', f.event_date)::date AS bucket,
               {INCIDENT_METRIC_EXPR[flt.metric]} AS value
        {FROM_INCIDENTS} WHERE {where} AND {col} = ANY(:codes) GROUP BY 1, 2 ORDER BY 1, 2""",
        {**params, "codes": codes})


def newly_targeted_villages(db: Session, flt: Filters, limit: int = 200) -> list[dict[str, Any]]:
    """Villages whose first incident ever (same filters, any earlier date) falls in the period."""
    where, params = incident_where(flt, date_from=date(1900, 1, 1), date_to=flt.date_to)
    return rows(db, f"""
        WITH v AS (
            SELECT f.admin_village_code AS code, MIN(f.event_date) FILTER (WHERE f.incidents > 0) AS first_date
            {FROM_INCIDENTS} WHERE {where} AND f.admin_village_code IS NOT NULL GROUP BY 1
        ), since AS (
            SELECT f.admin_village_code AS code, SUM(f.incidents) AS incidents
            {FROM_INCIDENTS} JOIN v ON v.code = f.admin_village_code
            WHERE {where} AND f.event_date >= v.first_date GROUP BY 1
        )
        SELECT v.code, a.name_en, a.name_ar, c.code AS caza_code, c.name_en AS caza_en, c.name_ar AS caza_ar,
               v.first_date, since.incidents AS incidents_since
        FROM v JOIN since ON since.code = v.code JOIN admin_areas a ON a.code = v.code
        LEFT JOIN admin_areas c ON c.code = a.caza_code
        WHERE v.first_date BETWEEN :period_from AND :d_to
        ORDER BY v.first_date DESC, since.incidents DESC, a.name_en LIMIT :limit""",
        {**params, "period_from": flt.date_from, "limit": limit})


def village_pareto(db: Session, flt: Filters, limit: int = 500) -> list[dict[str, Any]]:
    """Villages by metric (desc) with the cumulative share of the total."""
    where, params = incident_where(flt)
    expr = INCIDENT_METRIC_EXPR[flt.metric if flt.metric != "breaches" else "incidents"]
    return rows(db, f"""
        WITH t AS (
            SELECT f.admin_village_code AS code, {expr} AS value
            {FROM_INCIDENTS} WHERE {where} AND f.admin_village_code IS NOT NULL GROUP BY 1 HAVING {expr} > 0
        ), r AS (
            SELECT code, value, row_number() OVER (ORDER BY value DESC, code) AS rank,
                   SUM(value) OVER (ORDER BY value DESC, code ROWS UNBOUNDED PRECEDING) AS cumulative,
                   SUM(value) OVER () AS total
            FROM t
        )
        SELECT r.code, a.name_en, a.name_ar, r.value, r.rank, r.cumulative,
               round(r.cumulative * 100.0 / NULLIF(r.total, 0), 1) AS cumulative_pct, r.total
        FROM r JOIN admin_areas a ON a.code = r.code ORDER BY r.rank LIMIT :limit""", {**params, "limit": limit})


def weekday_series(db: Session, flt: Filters) -> list[dict[str, Any]]:
    """Metric by ISO day of week (1 = Monday) of the event date."""
    where, params = incident_where(flt)
    expr = INCIDENT_METRIC_EXPR[flt.metric if flt.metric != "breaches" else "incidents"]
    return rows(db, f"""SELECT extract(isodow FROM f.event_date)::int AS dow, {expr} AS value,
                               count(DISTINCT f.event_date) AS days
                        {FROM_INCIDENTS} WHERE {where} GROUP BY 1 ORDER BY 1""", params)


def weekly_area_ranks(db: Session, flt: Filters, level: str = "caza") -> list[dict[str, Any]]:
    """Metric per area per week, with the area's rank inside each week."""
    where, params = incident_where(flt)
    col = INCIDENT_LEVEL_COL[level]
    expr = INCIDENT_METRIC_EXPR[flt.metric if flt.metric != "breaches" else "incidents"]
    return rows(db, f"""
        WITH t AS (
            SELECT date_trunc('week', f.event_date)::date AS week, {col} AS code, {expr} AS value
            {FROM_INCIDENTS} WHERE {where} AND {col} IS NOT NULL GROUP BY 1, 2 HAVING {expr} > 0
        )
        SELECT t.week, t.code, a.name_en, a.name_ar, t.value,
               rank() OVER (PARTITION BY t.week ORDER BY t.value DESC) AS rank
        FROM t JOIN admin_areas a ON a.code = t.code ORDER BY t.week, rank, a.name_en""", params)


def monthly_incident_totals(db: Session, flt: Filters) -> list[dict[str, Any]]:
    where, params = incident_where(flt)
    return rows(db, f"""
        SELECT date_trunc('month', f.event_date)::date AS month, SUM(f.incidents) AS incidents,
               SUM(f.deaths_total) AS deaths, SUM(f.injuries_total) AS injuries,
               count(DISTINCT f.village_id) FILTER (WHERE f.incidents > 0) AS villages
        {FROM_INCIDENTS} WHERE {where} GROUP BY 1 ORDER BY 1""", params)


def monthly_air_totals(db: Session, flt: Filters) -> list[dict[str, Any]]:
    where, params = air_where(flt)
    return rows(db, f"""SELECT date_trunc('month', a.breach_date)::date AS month, SUM(a.breaches) AS breaches
                        {FROM_AIR} WHERE {where} GROUP BY 1 ORDER BY 1""", params)


def air_by_area_and_type(db: Session, flt: Filters, level: str) -> list[dict[str, Any]]:
    """Breaches per area x air type, following the per-level counting units."""
    col, pred = air_level_columns(level)
    where, params = air_where(flt, conditions=AIR_LEVEL_CONDITIONS[level])
    return rows(db, f"""
        WITH t AS (
            SELECT {col} AS code, a.condition_id, SUM(a.breaches) AS breaches
            {FROM_AIR} WHERE {where} AND {pred} AND {col} IS NOT NULL GROUP BY 1, 2
        )
        SELECT t.code, ar.name_en, ar.name_ar, p.name_en AS parent_name_en, t.condition_id, t.breaches
        FROM t JOIN admin_areas ar ON ar.code = t.code LEFT JOIN admin_areas p ON p.code = ar.parent_code
        ORDER BY t.code, t.condition_id""", params)


def air_reports_by_hour(db: Session, flt: Filters, condition_ids: list[int]) -> list[dict[str, Any]]:
    """Air-violation REPORTS by hour of the report time (Beirut), per type; not breaches.

    Rows are the Air Violations page selection (supported conditions). The area filter
    matches reports through their named villages; a report that names no village (e.g. a
    caza-only balloon report) is left out when an area is selected.
    """
    clauses = ["v.event_date BETWEEN :d_from AND :d_to", "v.condition_id = ANY(:conds)", "v.event_time IS NOT NULL"]
    params: dict[str, Any] = {"d_from": flt.date_from, "d_to": flt.date_to, "conds": condition_ids}
    if flt.area_code:
        column = {"mohafaza": "aa.mohafaza_code", "caza": "aa.caza_code", "village": "aa.code"}[flt.area_level]
        clauses.append(f"""EXISTS (
            SELECT 1 FROM villages vl JOIN admin_areas aa ON aa.code = vl.admin_area_code
            WHERE (vl.id = v.village_id OR vl.id IN (SELECT l.village_id FROM air_violation_locations l
                                                     WHERE l.air_violation_id = v.id))
              AND {column} = :area)""")
        params["area"] = flt.area_code
    return rows(db, f"""
        SELECT v.condition_id, extract(hour FROM v.event_time)::int AS hour, count(*) AS reports
        FROM air_violations v WHERE {' AND '.join(clauses)} GROUP BY 1, 2 ORDER BY 1, 2""", params)


def source_last_messages(db: Session, limit: int = 25) -> list[dict[str, Any]]:
    """Latest message time per channel (ingestion freshness)."""
    return rows(db, """
        SELECT coalesce(source_name, 'unknown') AS channel, max(source_platform) AS platform,
               max(message_datetime) AS last_message,
               count(*) FILTER (WHERE message_datetime >= now() - interval '24 hours') AS last_24h
        FROM raw_messages GROUP BY 1 ORDER BY last_message DESC NULLS LAST LIMIT :limit""", {"limit": limit})
