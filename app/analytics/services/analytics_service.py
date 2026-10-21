"""Shapes the Analytics API responses from the repository queries (cached in Redis)."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Callable

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.analytics.constants import (
    AIR_CONDITION_LABELS, AIR_LEVEL_CONDITIONS, CONFLICT_ZONE_CAZAS, CONFLICT_ZONE_MOHAFAZAT,
)
from app.analytics.dtos.filters import Filters, params_hash
from app.analytics.repositories import analytics_repository as repo
from app.core import cache
from app.core.config import settings

logger = logging.getLogger(__name__)

CACHE_VERSION_KEY = "analytics:version"
INCIDENT_METRICS = ("incidents", "deaths", "injuries", "casualties")
AIR_RULE_TEXT = {
    "mohafaza": "Mohafaza level shows all air-violation types.",
    "caza": "Caza level shows drones/surveillance, spy balloons and helicopters. Warplane breaches are counted per mohafaza only.",
    "village": "Village level shows helicopters only. Warplane and drone breaches are never split below mohafaza/caza.",
}


def cached(route: str, params: dict[str, Any], build: Callable[[], Any]) -> Any:
    key = f"analytics:{cache.get_cache_version(CACHE_VERSION_KEY)}:{route}:{params_hash(params)}"
    hit = cache.get_json(key)
    if hit is not None:
        return hit
    payload = jsonable_encoder(build())
    cache.set_json(key, payload, settings.analytics_cache_ttl_seconds)
    return payload


def _num(value: Any) -> int | float:
    return int(value) if value is not None and float(value).is_integer() else float(value or 0)


# --------------------------------------------------------------------------- meta
def get_meta(db: Session) -> Any:
    return cached("meta", {}, lambda: repo.meta(db))


# --------------------------------------------------------------------------- map
def unsupported_air_message(level: str, bad: set[int]) -> str:
    names = ", ".join(AIR_CONDITION_LABELS.get(c, str(c)) for c in sorted(bad))
    return f"{names} cannot be shown at {level} level. {AIR_RULE_TEXT[level]}"


def get_map(db: Session, flt: Filters) -> Any:
    def build() -> dict[str, Any]:
        unit_note = "Incidents counted at the incident's village."
        if flt.metric == "breaches":
            allowed = AIR_LEVEL_CONDITIONS[flt.level]
            values = repo.map_air_values(db, flt, allowed)
            unit_note = "CNRS breaches. " + AIR_RULE_TEXT[flt.level]
        else:
            values = repo.map_incident_values(db, flt)
        codes = [v["code"] for v in values]
        breakdown = repo.incident_breakdown_by_area(db, flt, codes) if flt.metric != "breaches" and codes else {}
        return {
            "level": flt.level, "metric": flt.metric,
            "values": [{"code": v["code"], "value": _num(v["value"]), **(
                {"families": breakdown[v["code"]]} if v["code"] in breakdown else {})} for v in values],
            "unit_note": unit_note,
            "unsupported_air_levels": repo.unsupported_air_levels(),
        }

    if flt.metric == "breaches" and flt.condition_id:  # validate before the cache can answer
        bad = (set(flt.condition_id) - AIR_LEVEL_CONDITIONS[flt.level])
        if bad:
            raise HTTPException(422, unsupported_air_levels_detail(flt.level, bad))
    return cached("map", flt.cache_params(), build)


def unsupported_air_levels_detail(level: str, bad: set[int]) -> str:
    return unsupported_air_message(level, bad)


# --------------------------------------------------------------------------- kpis
def _delta(current: int | float, previous: int | float) -> dict[str, Any]:
    change = current - previous
    return {"current": current, "previous": previous, "delta": change,
            "pct": round(change / previous * 100, 1) if previous else None}


def get_kpis(db: Session, flt: Filters) -> Any:
    def build() -> dict[str, Any]:
        prev = flt.previous_period()
        cur_t, prev_t = repo.incident_totals(db, flt), repo.incident_totals(db, prev)
        cur_air, prev_air = repo.air_totals_by_condition(db, flt), repo.air_totals_by_condition(db, prev)
        pending = repo.pending_review_count(db, flt)
        span = flt.model_copy(update={"date_from": flt.date_to - timedelta(days=29)})
        rolling = repo.daily_incident_series(db, span, "incidents")
        by_day = {r["date"]: int(r["value"]) for r in rolling}
        total_30 = sum(by_day.values())
        today = by_day.get(flt.date_to, 0)
        avg = round(total_30 / 30, 2)
        breaches_total = sum(cur_air.values())
        return {
            "period": {"date_from": flt.date_from, "date_to": flt.date_to, "previous_from": prev.date_from,
                       "previous_to": prev.date_to, "days": flt.days},
            "incidents": _delta(int(cur_t["incidents"]), int(prev_t["incidents"])),
            "deaths": {**_delta(int(cur_t["deaths"]), int(prev_t["deaths"])),
                       "male": int(cur_t["deaths_male"]), "female": int(cur_t["deaths_female"]),
                       "children": int(cur_t["deaths_children"]), "unspecified": int(cur_t["deaths_unspecified"])},
            "injuries": {**_delta(int(cur_t["injuries"]), int(prev_t["injuries"])),
                         "male": int(cur_t["injuries_male"]), "female": int(cur_t["injuries_female"]),
                         "children": int(cur_t["injuries_children"]), "unspecified": int(cur_t["injuries_unspecified"])},
            "villages_affected": _delta(int(cur_t["villages_affected"]), int(prev_t["villages_affected"])),
            "cazas_affected": _delta(int(cur_t["cazas_affected"]), int(prev_t["cazas_affected"])),
            "air_breaches": {
                **_delta(breaches_total, sum(prev_air.values())),
                "by_type": [{"condition_id": c, "label": AIR_CONDITION_LABELS.get(c, str(c)),
                             "current": cur_air.get(c, 0), "previous": prev_air.get(c, 0)}
                            for c in sorted(AIR_CONDITION_LABELS)],
            },
            "pending_review": pending,
            "casualty_completeness": repo.casualty_completeness(db, flt),
            "unattributed_shared_toll_incidents": int(cur_t["aggregate_only_incidents"]),
            "escalation": {"today": today, "date": flt.date_to, "rolling_30d_daily_average": avg,
                           "ratio": round(today / avg, 2) if avg else None},
            "sparklines": {
                "incidents": [{"date": r["date"], "value": int(r["value"])} for r in repo.daily_incident_series(db, flt, "incidents")],
                "deaths": [{"date": r["date"], "value": int(r["value"])} for r in repo.daily_incident_series(db, flt, "deaths")],
                "injuries": [{"date": r["date"], "value": int(r["value"])} for r in repo.daily_incident_series(db, flt, "injuries")],
                "breaches": [{"date": r["date"], "value": int(r["value"])} for r in repo.daily_air_series(db, flt)],
            },
        }

    return cached("kpis", flt.cache_params(), build)


# --------------------------------------------------------------------------- coverage
LOW_COVERAGE = ("none", "low")
COVERAGE_NOTE = ("Hatched days had no or low ingestion (fewer raw messages than "
                 "{ratio:.0%} of the usual daily volume): missing data, not quiet days.")


def coverage_or_empty(db: Session, date_from: date, date_to: date) -> list[dict[str, Any]]:
    """Daily coverage; advisory, so a failure never breaks the section that asked for it."""
    try:
        return repo.coverage_days(db, date_from, date_to, settings.analytics_coverage_low_ratio)
    except Exception:
        db.rollback()
        logger.warning("analytics: ingest coverage signal unavailable", exc_info=True)
        return []


def get_coverage(db: Session, flt: Filters) -> Any:
    def build() -> dict[str, Any]:
        days = coverage_or_empty(db, flt.date_from, flt.date_to)
        return {
            "low_ratio": settings.analytics_coverage_low_ratio,
            "note": COVERAGE_NOTE.format(ratio=settings.analytics_coverage_low_ratio),
            "days": days,
            "low_days": sum(1 for d in days if d["status"] == "low"),
            "no_coverage_days": sum(1 for d in days if d["status"] == "none"),
        }

    return cached("coverage", {"date_from": flt.date_from.isoformat(), "date_to": flt.date_to.isoformat()}, build)


# --------------------------------------------------------------------------- timeline
def _bucket_starts(date_from: date, date_to: date, grain: str) -> list[date]:
    if grain == "day":
        start, step = date_from, None
    elif grain == "week":
        start = date_from - timedelta(days=date_from.weekday())
    else:
        start = date_from.replace(day=1)
    out, cur = [], start
    while cur <= date_to:
        out.append(cur)
        if grain == "day":
            cur += timedelta(days=1)
        elif grain == "week":
            cur += timedelta(days=7)
        else:
            cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


def _bucket_end(start: date, grain: str, limit: date) -> date:
    if grain == "day":
        end = start
    elif grain == "week":
        end = start + timedelta(days=6)
    else:
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return min(end, limit)


def get_timeline(db: Session, flt: Filters, grain: str) -> Any:
    def build() -> dict[str, Any]:
        starts = _bucket_starts(flt.date_from, flt.date_to, grain)
        if flt.metric == "breaches":
            raw = repo.timeline_air_series(db, flt, grain)
            labels = {str(c): {"label_en": n, "label_ar": None} for c, n in AIR_CONDITION_LABELS.items()}
            daily = repo.daily_air_series(db, flt)
        else:
            raw = repo.timeline_incident_series(db, flt, grain)
            labels = {f["code"]: {"label_en": f["name_en"], "label_ar": f["name_ar"], "sort": f["sort_order"]}
                      for f in repo.meta(db)["families"]}
            daily = repo.daily_incident_series(db, flt, flt.metric)
        series: dict[str, dict[date, float]] = {}
        for r in raw:
            series.setdefault(str(r["key"]), {})[r["bucket"]] = _num(r["value"])
        # A compact, stable legend: retain the five largest series and roll every
        # remaining family/type into Other.  This avoids a paginated legend hiding
        # categories while preserving every value in the stack and total.
        ranked_keys = sorted(series, key=lambda k: (-sum(series[k].values()), labels.get(k, {}).get("label_en", k), k))
        if len(ranked_keys) > 5:
            other: dict[date, float] = {}
            for key in ranked_keys[5:]:
                for bucket, value in series[key].items():
                    other[bucket] = other.get(bucket, 0) + value
            series = {key: series[key] for key in ranked_keys[:5]}
            series["other"] = other
            labels["other"] = {"label_en": "Other", "label_ar": None, "sort": 999}
        keys = list(series)
        total = {s: sum(series[k].get(s, 0) for k in keys) for s in starts}
        by_day = {r["date"]: float(r["value"]) for r in daily}
        ma: dict[date, float] = {}
        day = flt.date_from
        while day <= flt.date_to:
            window = [by_day.get(day - timedelta(days=i), 0.0) for i in range(7)]
            ma[day] = round(sum(window) / 7, 2)
            day += timedelta(days=1)
        days = coverage_or_empty(db, flt.date_from, flt.date_to)
        flagged = [d for d in days if d["status"] in LOW_COVERAGE]
        return {
            "grain": grain, "metric": flt.metric,
            "series": [{"key": k, **labels.get(k, {"label_en": k, "label_ar": None}),
                        "total": sum(series[k].values()),
                        "points": [{"date": s, "value": series[k].get(s, 0)} for s in starts]} for k in keys],
            "total": [{"date": s, "value": total[s]} for s in starts],
            "moving_average_7d": [{"date": s, "value": ma[_bucket_end(s, grain, flt.date_to)]} for s in starts],
            "coverage": {
                "available": bool(days),
                "note": COVERAGE_NOTE.format(ratio=settings.analytics_coverage_low_ratio),
                "gap_dates": [d["date"] for d in flagged],
                "flagged": [{"date": d["date"], "status": d["status"], "messages": d["messages"]} for d in flagged],
            },
        }

    return cached("timeline", {**flt.cache_params(), "grain": grain}, build)


# --------------------------------------------------------------------------- rankings
def get_rankings(db: Session, flt: Filters, limit: int) -> Any:
    def build() -> dict[str, Any]:
        if flt.metric == "breaches":
            data = repo.rank_air_areas(db, flt, flt.level, limit)
            for row in data:
                row["dominant_condition_label"] = AIR_CONDITION_LABELS.get(row["dominant_condition"])
                row["value"] = int(row["breaches"])
        else:
            data = repo.rank_incident_areas(db, flt, flt.level, limit)
            for row in data:
                row["value"] = int({"incidents": row["incidents"], "deaths": row["deaths"],
                                    "injuries": row["injuries"], "casualties": row["casualties"]}[flt.metric])
        # The query orders by the metric DESC (ties: name); the rank is fixed here so a
        # client re-sort by another column never renumbers it.
        for position, row in enumerate(data, start=1):
            row["rank"] = position
        return {"level": flt.level, "metric": flt.metric, "limit": limit, "rows": data}

    return cached("rankings", {**flt.cache_params(), "limit": limit}, build)


# --------------------------------------------------------------------------- peaks
def get_peaks(db: Session, flt: Filters) -> Any:
    def build() -> dict[str, Any]:
        coverage = {d["date"]: d["status"] for d in coverage_or_empty(db, flt.date_from, flt.date_to)}

        def low_days(start: date, unit: str) -> int:
            span = 7 if unit == "week" else 1
            return sum(1 for i in range(span) if coverage.get(start + timedelta(days=i)) in LOW_COVERAGE)

        result: dict[str, Any] = {}
        for metric in ("incidents", "deaths", "breaches"):
            entry: dict[str, Any] = {}
            for unit in ("day", "week"):
                peak = repo.peak_periods(db, flt, unit, metric)
                entry[unit] = None if not peak else {
                    "start": peak["start"], "value": _num(peak["value"]),
                    # A peak next to missing data may be an artefact of ingestion; the UI stars it.
                    "low_coverage_days": low_days(peak["start"], unit),
                    "top_areas": [{"code": a["code"], "name_en": a["name_en"], "name_ar": a["name_ar"],
                                   "value": _num(a["value"])}
                                  for a in repo.top_cazas_for_period(db, flt, peak["start"], unit, metric)],
                }
            result[metric] = entry
        return result

    return cached("peaks", flt.cache_params(), build)


# --------------------------------------------------------------------------- matrix
def get_matrix(db: Session, flt: Filters) -> Any:
    def build() -> dict[str, Any]:
        families = repo.meta(db)["families"]
        if flt.metric == "breaches":
            columns = [f for f in families if f["is_air_violation"]]
            cells = repo.matrix_air_cells(db, flt)
        else:
            # The incident matrix intentionally excludes air violations (shown on
            # their own tab) and unclassified/pending incidents. Empty columns add
            # no information and make the compact view harder to read.
            columns = [f for f in families if f["counts_in_headline"] and not f["is_air_violation"]
                       and (not flt.family or f["code"] in flt.family)]
            cells = repo.matrix_cells(db, flt)
        by_caza: dict[str, dict[str, int | float]] = {}
        for c in cells:
            by_caza.setdefault(c["caza"], {})[c["family"]] = _num(c["value"])
        rows_out = []
        col_totals = {c["code"]: 0 for c in columns}
        for caza in repo.caza_rows(db):
            vals = {c["code"]: by_caza.get(caza["code"], {}).get(c["code"], 0) for c in columns}
            for k, v in vals.items():
                col_totals[k] += v
            rows_out.append({**caza, "cells": vals, "total": sum(vals.values())})
        columns = [column for column in columns if col_totals[column["code"]] > 0]
        col_totals = {column["code"]: col_totals[column["code"]] for column in columns}
        for row in rows_out:
            row["cells"] = {column["code"]: row["cells"][column["code"]] for column in columns}
        return {"metric": flt.metric, "columns": columns, "rows": rows_out, "column_totals": col_totals,
                "grand_total": sum(col_totals.values())}

    return cached("matrix", flt.cache_params(), build)


# --------------------------------------------------------------------------- area profile
def get_area(db: Session, code: str, flt: Filters) -> Any:
    info = repo.area_info(db, code)
    if info is None:
        raise HTTPException(404, f"Unknown area {code!r}.")

    def build() -> dict[str, Any]:
        scoped = flt.model_copy(update={"area_code": code, "area_level": info["level"], "metric": "incidents"})
        totals = repo.incident_totals(db, scoped)
        child_level = repo.INCIDENT_CHILD_LEVEL.get(info["level"])
        children = []
        if child_level:
            children = repo.rank_incident_areas(db, scoped.model_copy(update={"metric": "incidents"}), child_level, 10)
        air = repo.air_totals_by_condition(db, scoped)
        return {
            "area": info,
            "totals": {k: int(v) for k, v in totals.items()},
            "pending_review": repo.pending_review_count(db, scoped),
            "casualty_completeness": repo.casualty_completeness(db, scoped),
            "air_breaches": {"total": sum(air.values()),
                             "by_type": [{"condition_id": c, "label": AIR_CONDITION_LABELS.get(c, str(c)), "value": v}
                                         for c, v in sorted(air.items())]},
            "families": repo.family_breakdown(db, scoped),
            "conditions": repo.condition_breakdown(db, scoped)[:12],
            "timeline": {
                "incidents": [{"date": r["date"], "value": int(r["value"])} for r in repo.daily_incident_series(db, scoped, "incidents")],
                "breaches": [{"date": r["date"], "value": int(r["value"])} for r in repo.daily_air_series(db, scoped)],
            },
            "top_children": {"level": child_level, "rows": children},
            "first_last_hit": repo.first_last_hit(db, scoped),
        }

    return cached("area", {**flt.cache_params(), "code": code}, build)


# --------------------------------------------------------------------------- drill-down
def get_incidents(db: Session, flt: Filters, page: int, page_size: int) -> Any:
    if flt.metric == "breaches":
        raise HTTPException(422, "Breaches are counted from air-violation reports; open the Air Violations page to see them.")

    def build() -> dict[str, Any]:
        total, data = repo.drilldown(db, flt, offset=(page - 1) * page_size, limit=page_size)
        return {"page": page, "page_size": page_size, "total": total, "items": data}

    return cached("incidents", {**flt.cache_params(), "page": page, "page_size": page_size}, build)


# --------------------------------------------------------------------------- data quality
def get_quality(db: Session, flt: Filters) -> Any:
    def build() -> dict[str, Any]:
        meta = repo.meta(db)
        return {
            "geo_anomalies": {
                "min_incidents": settings.analytics_geo_anomaly_min_incidents,
                "note": ("Villages outside the conflict zone (South, Nabatiye, Bekaa, Baalbek-Hermel, Baabda caza) "
                         "with more incidents than the threshold in this period, counted and pending. "
                         "Usually a wrong village match; open the incidents and check the place name."),
                "rows": repo.geo_anomalies(db, flt, settings.analytics_geo_anomaly_min_incidents,
                                           CONFLICT_ZONE_MOHAFAZAT, CONFLICT_ZONE_CAZAS),
            },
            "pending_review": repo.pending_review_count(db, flt),
            "archive_cutoff": meta["archive"]["cutoff_date"],
            "last_refresh": meta["last_refresh"],
            "refresh_queue": meta["refresh_queue"],
        }

    return cached("quality", flt.cache_params(), build)
