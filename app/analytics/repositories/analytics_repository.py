"""Read-side queries for the Analytics page.

Aggregates read only ``analytics_incident_facts``, ``analytics_air_breach_facts``,
``admin_areas`` and ``action_families``. The only raw-table reads are the drill-down
(``incidents`` / ``incidents_archive`` rows behind a number) and the ingest-coverage
signal (``raw_messages``). Every query is parameterised; the few identifiers that are
interpolated come from fixed whitelists in this module, never from request input.
"""
from __future__ import annotations

from datetime import date
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
    date_from: date | None = None, date_to: date | None = None,
) -> tuple[str, dict[str, Any]]:
    """WHERE clause over ``analytics_incident_facts f JOIN action_families af``."""
    clauses = ["f.event_date BETWEEN :d_from AND :d_to"]
    params: dict[str, Any] = {"d_from": date_from or flt.date_from, "d_to": date_to or flt.date_to}
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
    pending = one(db, """
        SELECT coalesce(sum(incidents) FILTER (WHERE bucket = 'pending'), 0) AS pending_incidents,
               coalesce(sum(incidents) FILTER (WHERE bucket = 'pending' AND source = 'live'), 0) AS pending_live
        FROM analytics_incident_facts""", {})
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
        "pending_review": {"incidents": int(pending["pending_incidents"]), "live": int(pending["pending_live"])},
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


def pending_incident_count(db: Session, flt: Filters) -> int:
    where, params = incident_where(flt, pending_only=True)
    return int(one(db, f"SELECT coalesce(SUM(f.incidents), 0) AS n {FROM_INCIDENTS} WHERE {where}", params)["n"])


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


def ingest_coverage(db: Session, date_from: date, date_to: date) -> list[date]:
    """Beirut days in the range with no ingested message at all (a coverage gap signal)."""
    present = {r["day"] for r in rows(db, """
        SELECT DISTINCT (message_datetime AT TIME ZONE 'Asia/Beirut')::date AS day FROM raw_messages
        WHERE message_datetime >= CAST(:a AS date) AND message_datetime < CAST(:b AS date) + 1""",
        {"a": date_from, "b": date_to})}
    if not present:
        return []
    gaps, day = [], date_from
    while day <= date_to:
        if day not in present and min(present) <= day <= max(present):
            gaps.append(day)
        day = date.fromordinal(day.toordinal() + 1)
    return gaps


# --------------------------------------------------------------------------- rankings
def rank_incident_areas(db: Session, flt: Filters, level: str, limit: int) -> list[dict[str, Any]]:
    where, params = incident_where(flt)
    col = INCIDENT_LEVEL_COL[level]
    order = {"incidents": "t.incidents", "deaths": "t.deaths", "injuries": "t.injuries",
             "casualties": "(t.deaths + t.injuries)"}[flt.metric if flt.metric != "breaches" else "incidents"]
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
        )
        SELECT t.code, a.level, a.name_en, a.name_ar, p.name_en AS parent_name_en, p.name_ar AS parent_name_ar,
               t.incidents, t.deaths, t.injuries, (t.deaths + t.injuries) AS casualties,
               t.first_date, t.last_date, dom.family AS dominant_family
        FROM t JOIN dom ON dom.code = t.code JOIN admin_areas a ON a.code = t.code
        LEFT JOIN admin_areas p ON p.code = a.parent_code
        WHERE {order} > 0
        ORDER BY {order} DESC, t.incidents DESC, t.code LIMIT :limit""", {**params, "limit": limit})


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
        ), dom AS (SELECT DISTINCT ON (code) code, condition_id FROM base ORDER BY code, n DESC, condition_id)
        SELECT t.code, a.level, a.name_en, a.name_ar, p.name_en AS parent_name_en, p.name_ar AS parent_name_ar,
               t.breaches, t.first_date, t.last_date, dom.condition_id AS dominant_condition
        FROM t JOIN dom ON dom.code = t.code JOIN admin_areas a ON a.code = t.code
        LEFT JOIN admin_areas p ON p.code = a.parent_code
        ORDER BY t.breaches DESC, t.code LIMIT :limit""", {**params, "limit": limit})


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
def matrix_cells(db: Session, flt: Filters) -> list[dict[str, Any]]:
    where, params = incident_where(flt)
    return rows(db, f"""
        SELECT f.caza_code AS caza, af.code AS family, {INCIDENT_METRIC_EXPR[flt.metric]} AS value
        {FROM_INCIDENTS} WHERE {where} AND f.caza_code IS NOT NULL GROUP BY f.caza_code, af.code""", params)


def matrix_air_cells(db: Session, flt: Filters) -> list[dict[str, Any]]:
    where, params = air_where(flt)
    return rows(db, f"""
        SELECT a.caza_code AS caza, 'air_violations' AS family, SUM(a.breaches) AS value
        {FROM_AIR} WHERE {where} AND a.unit_level IN ('caza', 'village') AND a.caza_code IS NOT NULL
        GROUP BY a.caza_code""", params)


def caza_rows(db: Session) -> list[dict[str, Any]]:
    return rows(db, """SELECT a.code, a.name_en, a.name_ar, a.mohafaza_code FROM admin_areas a
                       WHERE level = 'caza' ORDER BY a.name_en""", {})


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


# --------------------------------------------------------------------------- drill-down
_DRILL_CTE = """
WITH src AS (
    SELECT i.id, i.event_date, i.event_time, i.village_id, i.condition_id, i.verification_status, i.is_deleted,
           i.total_deaths, i.total_injuries, i.khabar, 'live' AS source, NULL::text AS archive_batch
    FROM incidents i WHERE NOT EXISTS (SELECT 1 FROM incidents_archive x WHERE x.id = i.id)
    UNION ALL
    SELECT a.id, a.event_date, a.event_time, a.village_id, a.condition_id, a.verification_status, a.is_deleted,
           a.total_deaths, a.total_injuries, a.khabar, 'archive', a.archive_batch
    FROM incidents_archive a
), joined AS (
    SELECT s.*, v.ref_name_en AS village_en, v.ref_name_ar AS village_ar, aa.code AS admin_village_code,
           aa.caza_code, aa.mohafaza_code, c.action_en, c.action_ar,
           af.code AS family, {bucket} AS bucket
    FROM src s
    JOIN conditions c ON c.id = s.condition_id
    LEFT JOIN condition_families cf ON cf.condition_id = s.condition_id
    LEFT JOIN action_families uf ON uf.code = 'unclassified'
    JOIN action_families af ON af.id = COALESCE(cf.family_id, uf.id)
    LEFT JOIN villages v ON v.id = s.village_id
    LEFT JOIN admin_areas aa ON aa.code = v.admin_area_code
)
"""


def drilldown(db: Session, flt: Filters, *, offset: int, limit: int) -> tuple[int, list[dict[str, Any]]]:
    bucket = bucket_sql("s.verification_status", "s.is_deleted", "af.counts_in_headline")
    clauses = ["j.bucket IS NOT NULL", "j.event_date BETWEEN :d_from AND :d_to"]
    params: dict[str, Any] = {"d_from": flt.date_from, "d_to": flt.date_to}
    if not flt.include_pending:
        clauses.append("j.bucket = 'counted'")
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
    if flt.metric == "deaths":
        clauses.append("coalesce(j.total_deaths, 0) > 0")
    elif flt.metric == "injuries":
        clauses.append("coalesce(j.total_injuries, 0) > 0")
    elif flt.metric == "casualties":
        clauses.append("coalesce(j.total_deaths, 0) + coalesce(j.total_injuries, 0) > 0")
    cte = _DRILL_CTE.format(bucket=bucket)
    where = " AND ".join(clauses)
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
