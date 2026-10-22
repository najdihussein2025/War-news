"""One payload per Analytics tab: everything the tab draws, from one request.

Every section takes the same ``Filters`` (dates, level, area, families, air type, pending,
metric) and aggregates in SQL; Python only zero-fills buckets and reshapes rows. Each tab
is cached as a whole under the shared analytics cache version (bumped by every refresh),
and the sections it reuses (KPIs, map, timeline, peaks, matrix) keep their own cache keys.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Callable

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.analytics.constants import AIR_CONDITION_LABELS, AIR_LEVEL_CONDITIONS
from app.analytics.dtos.filters import Filters
from app.analytics.repositories import analytics_repository as repo
from app.analytics.services import analytics_service as svc
from app.analytics.services import verification_reason_categories as reasons
from app.news.services.air_violations.war_month import war_month

TABS = ("overview", "map", "incidents", "casualties", "air", "quality")
RANKING_LIMIT = 100
CASUALTY_INCIDENT_LIMIT = 500
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
AIR_FAMILY = "air_violations"
HOUR_NOTE = ("Hour the report was received (Beirut time), not the time of the event. "
             "Counts reports, not breaches.")


def _int(value: Any) -> int:
    return int(value or 0)


def _pct_change(current: float, previous: float) -> float | None:
    return round((current - previous) / previous * 100, 1) if previous else None


def _zero_fill(starts: list[date], values: dict[date, Any]) -> list[dict[str, Any]]:
    return [{"date": s, "value": svc._num(values.get(s, 0))} for s in starts]


def _incident_metric(flt: Filters) -> str:
    return flt.metric if flt.metric != "breaches" else "incidents"


def _metric_total(totals: dict[str, Any], metric: str) -> int:
    if metric == "casualties":
        return _int(totals["deaths"]) + _int(totals["injuries"])
    return _int(totals[metric])


# --------------------------------------------------------------------------- overview
def _action_trend(db: Session, flt: Filters, grain: str) -> dict[str, Any]:
    starts = svc._bucket_starts(flt.date_from, flt.date_to, grain)
    series, labels = svc._series_by_key(db, flt, grain)
    out = [{"key": k, **labels.get(k, {"label_en": k, "label_ar": None}), "total": sum(v.values()),
            "points": _zero_fill(starts, v)} for k, v in series.items()]
    out.sort(key=lambda s: (-s["total"], s["key"]))
    return {"grain": grain, "metric": flt.metric, "series": out,
            "max_point": max((p["value"] for s in out for p in s["points"]), default=0)}


def _action_share(db: Session, flt: Filters) -> dict[str, Any]:
    if flt.metric == "breaches":
        totals = repo.air_totals_by_condition(db, flt)
        rows = [{"key": str(c), "label_en": AIR_CONDITION_LABELS.get(c, str(c)), "value": n}
                for c, n in sorted(totals.items()) if n]
    else:
        metric = _incident_metric(flt)
        rows = [{"key": r["code"], "label_en": r["name_en"], "label_ar": r["name_ar"],
                 "value": _int(r["deaths"]) + _int(r["injuries"]) if metric == "casualties"
                 else _int(r[metric])} for r in repo.family_breakdown(db, flt)]
        rows = [r for r in rows if r["value"]]
    total = sum(r["value"] for r in rows)
    for r in rows:
        r["share_pct"] = round(r["value"] / total * 100, 1) if total else None
    rows.sort(key=lambda r: -r["value"])
    return {"metric": flt.metric, "total": total, "rows": rows}


def _period_comparison(db: Session, flt: Filters) -> dict[str, Any]:
    prev = flt.previous_period()
    raw = repo.air_area_period_comparison(db, flt, "caza") if flt.metric == "breaches" \
        else repo.area_period_comparison(db, flt, "caza")
    rows = [{"code": r["code"], "name_en": r["name_en"], "name_ar": r["name_ar"],
             "current": svc._num(r["current"]), "previous": svc._num(r["previous"]),
             "delta": svc._num(r["current"]) - svc._num(r["previous"]),
             "pct": _pct_change(svc._num(r["current"]), svc._num(r["previous"]))} for r in raw]
    return {"level": "caza", "metric": flt.metric, "period": {"date_from": flt.date_from, "date_to": flt.date_to},
            "previous": {"date_from": prev.date_from, "date_to": prev.date_to}, "rows": rows}


def build_overview(db: Session, flt: Filters, grain: str) -> dict[str, Any]:
    return {
        "kpis": svc.get_kpis(db, flt),
        "map": svc.get_map(db, flt.model_copy(update={"area_code": None, "area_level": None})),
        "top_areas": svc.get_rankings(db, flt.model_copy(update={"area_code": None, "area_level": None}), 10),
        "timeline": svc.get_timeline(db, flt, grain),
        "peaks": svc.get_peaks(db, flt),
        "action_share": _action_share(db, flt),
        "action_trend": _action_trend(db, flt, grain),
        "period_comparison": _period_comparison(db, flt),
    }


# --------------------------------------------------------------------------- map
def _ranking_views(flt: Filters) -> list[tuple[str, str, str, str]]:
    """(id, label, level, metric): the Rankings tabs; breaches rank air breaches at each level."""
    if flt.metric == "breaches":
        return [("villages", "Villages (helicopters)", "village", "breaches"),
                ("caza", "By caza", "caza", "breaches"), ("mohafaza", "By mohafaza", "mohafaza", "breaches")]
    metric = flt.metric
    return [("villages", "Most hit villages", "village", "incidents"), ("deaths", "Most deaths", "village", "deaths"),
            ("injuries", "Most injuries", "village", "injuries"), ("caza", "By caza", "caza", metric),
            ("mohafaza", "By mohafaza", "mohafaza", metric)]


def _ranking(db: Session, flt: Filters, view: tuple[str, str, str, str], starts: list[date]) -> dict[str, Any]:
    view_id, label, level, metric = view
    scoped = flt.model_copy(update={"metric": metric, "level": level, "area_code": None, "area_level": None})
    if metric == "breaches":
        rows = repo.rank_air_areas(db, scoped, level, RANKING_LIMIT)
        for r in rows:
            r["value"] = _int(r["breaches"])
            r["dominant_condition_label"] = AIR_CONDITION_LABELS.get(r["dominant_condition"])
        total = sum(v for c, v in repo.air_totals_by_condition(db, scoped).items()
                    if c in AIR_LEVEL_CONDITIONS[level])
    else:
        rows = repo.rank_incident_areas(db, scoped, level, RANKING_LIMIT)
        for r in rows:
            r["value"] = _int(r["casualties"] if metric == "casualties" else r[metric])
        total = _metric_total(repo.incident_totals(db, scoped), metric)
    weekly: dict[str, dict[date, Any]] = {}
    for w in repo.area_week_series(db, scoped, level, [r["code"] for r in rows]):
        weekly.setdefault(w["code"], {})[w["bucket"]] = w["value"]
    for position, r in enumerate(rows, start=1):
        r["rank"] = position
        r["share_pct"] = round(r["value"] / total * 100, 1) if total else None
        r["days_hit"] = _int(r.get("days_hit"))
        r["last_7d"] = svc._num(r.get("last_7d"))
        r["trend"] = [svc._num(weekly.get(r["code"], {}).get(s, 0)) for s in starts]
    return {"id": view_id, "label": label, "level": level, "metric": metric, "total": total, "rows": rows}


def _pareto(db: Session, flt: Filters) -> dict[str, Any]:
    rows = repo.village_pareto(db, flt)
    total = svc._num(rows[0]["total"]) if rows else 0

    def villages_for(pct: float) -> int | None:
        return next((r["rank"] for r in rows if (r["cumulative_pct"] or 0) >= pct), None)

    top10 = rows[min(9, len(rows) - 1)]["cumulative_pct"] if rows else None
    return {
        "metric": _incident_metric(flt), "total": total, "villages_hit": len(rows),
        "summary": {"top10_share_pct": top10, "villages_for_50_pct": villages_for(50),
                    "villages_for_80_pct": villages_for(80)},
        "rows": [{"code": r["code"], "name_en": r["name_en"], "name_ar": r["name_ar"], "value": svc._num(r["value"]),
                  "rank": r["rank"], "cumulative_pct": float(r["cumulative_pct"] or 0)} for r in rows],
    }


def build_map(db: Session, flt: Filters, grain: str) -> dict[str, Any]:
    starts = svc._bucket_starts(flt.date_from, flt.date_to, "week")
    return {
        "map": svc.get_map(db, flt.model_copy(update={"area_code": None, "area_level": None})),
        "rankings": {"weeks": starts, "views": [_ranking(db, flt, v, starts) for v in _ranking_views(flt)]},
        "newly_targeted": {"rows": repo.newly_targeted_villages(db, flt),
                           "note": "Villages whose first recorded incident (same filters) falls in this period."},
        "pareto": _pareto(db, flt),
    }


# --------------------------------------------------------------------------- incidents
def _weekly_caza(db: Session, flt: Filters) -> dict[str, Any]:
    weeks = svc._bucket_starts(flt.date_from, flt.date_to, "week")
    by_code: dict[str, dict[str, Any]] = {}
    for r in repo.weekly_area_ranks(db, flt, "caza"):
        entry = by_code.setdefault(r["code"], {"code": r["code"], "name_en": r["name_en"], "name_ar": r["name_ar"],
                                               "points": {}})
        entry["points"][r["week"]] = (svc._num(r["value"]), int(r["rank"]))
    series = []
    for entry in by_code.values():
        points = [{"week": w, "value": entry["points"].get(w, (0, None))[0],
                   "rank": entry["points"].get(w, (0, None))[1]} for w in weeks]
        series.append({**{k: entry[k] for k in ("code", "name_en", "name_ar")},
                       "total": sum(p["value"] for p in points), "points": points})
    series.sort(key=lambda s: (-s["total"], s["name_en"] or ""))
    return {"metric": _incident_metric(flt), "weeks": weeks, "series": series}


def _channels(db: Session, flt: Filters) -> dict[str, Any]:
    rows = repo.channel_breakdown(db, flt)
    total = sum(_int(r["incidents"]) for r in rows)
    return {"total": total, "rows": [{**r, "incidents": _int(r["incidents"]), "deaths": _int(r["deaths"]),
                                      "injuries": _int(r["injuries"]),
                                      "share_pct": round(_int(r["incidents"]) / total * 100, 1) if total else None}
                                     for r in rows],
            "note": "Channel that published the message each incident was extracted from."}


def _war_months(db: Session, flt: Filters) -> dict[str, Any]:
    incidents = {r["month"]: r for r in repo.monthly_incident_totals(db, flt)}
    breaches = {r["month"]: _int(r["breaches"]) for r in repo.monthly_air_totals(db, flt)}
    out: list[dict[str, Any]] = []
    for month in sorted(set(incidents) | set(breaches)):
        r = incidents.get(month, {})
        month_end = (month + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        row = {"month": month, "war_month": war_month(month), "label": month.strftime("%B %Y"),
               # The period cuts this month: its totals cover only part of it.
               "partial": month < flt.date_from or month_end > flt.date_to,
               "incidents": _int(r.get("incidents")), "deaths": _int(r.get("deaths")),
               "injuries": _int(r.get("injuries")), "villages": _int(r.get("villages")),
               "breaches": breaches.get(month, 0)}
        if not any(row[k] for k in ("incidents", "deaths", "injuries", "breaches")):
            continue  # only months with data
        prev = out[-1] if out and (out[-1]["month"] + timedelta(days=32)).replace(day=1) == month else None
        row["delta"] = {k: (row[k] - prev[k]) if prev else None
                        for k in ("incidents", "deaths", "injuries", "breaches", "villages")}
        out.append(row)
    meta = repo.meta(db)
    return {"data_starts": meta["incident_data"]["first_date"], "rows": out,
            "note": "War month 1 = April. Months are calendar months in the selected period."}


def build_incidents(db: Session, flt: Filters, grain: str) -> dict[str, Any]:
    weekday = {r["dow"]: r for r in repo.weekday_series(db, flt)}
    return {
        "timeline": svc.get_timeline(db, flt, grain),
        "peaks": svc.get_peaks(db, flt),
        "matrix_caza": svc.get_matrix(db, flt, "caza"),
        "matrix_mohafaza": svc.get_matrix(db, flt, "mohafaza"),
        "weekday": {"metric": _incident_metric(flt), "note": "Day of the week of the incident date.",
                    "rows": [{"dow": i, "label": WEEKDAYS[i - 1], "value": svc._num(weekday.get(i, {}).get("value", 0)),
                              "days": _int(weekday.get(i, {}).get("days"))} for i in range(1, 8)]},
        "weekly_caza": _weekly_caza(db, flt),
        "channels": _channels(db, flt),
        "war_months": _war_months(db, flt),
    }


# --------------------------------------------------------------------------- casualties
def build_casualties(db: Session, flt: Filters, grain: str) -> dict[str, Any]:
    starts = svc._bucket_starts(flt.date_from, flt.date_to, grain)
    series = {r["bucket"]: r for r in repo.casualty_series(db, flt, grain)}
    total, incidents = repo.casualty_incidents(db, flt, CASUALTY_INCIDENT_LIMIT)
    return {
        "kpis": svc.get_kpis(db, flt),
        "completeness": repo.casualty_completeness(db, flt),
        "series": {"grain": grain, "points": [{"date": s, "deaths": _int(series.get(s, {}).get("deaths")),
                                               "injuries": _int(series.get(s, {}).get("injuries"))} for s in starts]},
        "by_caza": [{k: (svc._num(v) if k not in ("code", "name_en", "name_ar") else v) for k, v in r.items()}
                    for r in repo.casualties_by_area(db, flt, "caza")],
        "by_family": [{"code": r["code"], "name_en": r["name_en"], "name_ar": r["name_ar"],
                       "deaths": _int(r["deaths"]), "injuries": _int(r["injuries"])}
                      for r in repo.family_breakdown(db, flt) if _int(r["deaths"]) + _int(r["injuries"]) > 0],
        "incidents": {"total": total, "limit": CASUALTY_INCIDENT_LIMIT, "rows": incidents},
    }


# --------------------------------------------------------------------------- air
def _air_level(flt: Filters) -> str:
    """The requested level if the selected air type can be shown there, else mohafaza."""
    wanted = set(flt.condition_id)
    return flt.level if not wanted or wanted <= AIR_LEVEL_CONDITIONS[flt.level] else "mohafaza"


def _air_areas(db: Session, flt: Filters, level: str) -> list[dict[str, Any]]:
    areas: dict[str, dict[str, Any]] = {}
    for r in repo.air_by_area_and_type(db, flt, level):
        entry = areas.setdefault(r["code"], {"code": r["code"], "name_en": r["name_en"], "name_ar": r["name_ar"],
                                             "parent_name_en": r["parent_name_en"], "total": 0, "by_type": {}})
        entry["by_type"][str(r["condition_id"])] = _int(r["breaches"])
        entry["total"] += _int(r["breaches"])
    return sorted(areas.values(), key=lambda a: (-a["total"], a["name_en"] or ""))


def _hour_reported(db: Session, flt: Filters) -> dict[str, Any]:
    if flt.family and AIR_FAMILY not in flt.family:
        wanted: list[int] = []
    else:
        wanted = sorted(set(flt.condition_id) & set(AIR_CONDITION_LABELS)) if flt.condition_id \
            else sorted(AIR_CONDITION_LABELS)
    hours: dict[int, list[int]] = {c: [0] * 24 for c in wanted}
    for r in repo.air_reports_by_hour(db, flt, wanted) if wanted else []:
        hours[int(r["condition_id"])][int(r["hour"])] = _int(r["reports"])
    return {"note": HOUR_NOTE, "types": [{"condition_id": c, "label": AIR_CONDITION_LABELS[c], "hours": h,
                                          "total": sum(h)} for c, h in hours.items()]}


def build_air(db: Session, flt: Filters, grain: str) -> dict[str, Any]:
    air = flt.model_copy(update={"metric": "breaches"})
    prev = air.previous_period()
    cur_t, prev_t = repo.air_totals_by_condition(db, air), repo.air_totals_by_condition(db, prev)
    level = _air_level(air)
    return {
        "total": svc._delta(sum(cur_t.values()), sum(prev_t.values())),
        "by_type": [{"condition_id": c, "label": label, **svc._delta(cur_t.get(c, 0), prev_t.get(c, 0))}
                    for c, label in sorted(AIR_CONDITION_LABELS.items())],
        "timeline": svc.get_timeline(db, air, grain),
        "by_mohafaza": _air_areas(db, air, "mohafaza"),
        "by_caza": _air_areas(db, air, "caza"),
        "top_villages": _air_areas(db, air, "village")[:50],
        "map": svc.get_map(db, air.model_copy(update={"level": level, "area_code": None, "area_level": None})),
        "hour_reported": _hour_reported(db, air),
        "level_rules": svc.AIR_RULE_TEXT,
        "labels": {str(c): n for c, n in AIR_CONDITION_LABELS.items()},
    }


# --------------------------------------------------------------------------- quality
def build_quality(db: Session, flt: Filters, grain: str) -> dict[str, Any]:
    starts = svc._bucket_starts(flt.date_from, flt.date_to, "day")
    pending = {r["date"]: r["value"] for r in repo.daily_pending_series(db, flt)}
    reason_rows = repo.review_reason_counts(db, flt, reasons.case_sql("j.verification_reason"))
    base = svc.get_quality(db, flt)
    return {
        "pending_review": base["pending_review"],
        "pending_series": _zero_fill(starts, pending),
        "review_reasons": [{"category": r["category"], "label": reasons.LABELS.get(r["category"], r["category"]),
                            "incidents": _int(r["incidents"])} for r in reason_rows],
        "village_matches": repo.village_match_counts(db, flt),
        "casualty_completeness": repo.casualty_completeness(db, flt),
        "coverage": svc.get_coverage(db, flt),
        "geo_anomalies": base["geo_anomalies"],
        "freshness": {"last_refresh": base["last_refresh"], "archive_cutoff": base["archive_cutoff"],
                      "queued_dates": repo.queued_dates(db), "sources": repo.source_last_messages(db)},
    }


BUILDERS: dict[str, Callable[[Session, Filters, str], dict[str, Any]]] = {
    "overview": build_overview, "map": build_map, "incidents": build_incidents,
    "casualties": build_casualties, "air": build_air, "quality": build_quality,
}


def get_tab(db: Session, tab: str, flt: Filters, grain: str) -> Any:
    if tab not in BUILDERS:
        raise HTTPException(404, f"Unknown analytics tab {tab!r}.")
    return svc.cached(f"tab:{tab}", {**flt.cache_params(), "grain": grain}, lambda: BUILDERS[tab](db, flt, grain))
