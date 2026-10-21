"""Build ``analytics_air_breach_facts`` from the CNRS breach counting service.

Reports are loaded exactly the way the Air Violations page loads them
(``AirViolationRepository._load_items(supported_only=True)``, the same row
selection and village labelling), counted by ``compute_breaches``, then each
breach is attributed to its counting unit:

* warplane (35)        -> mohafaza
* drone/surveillance (36) and spy balloon (34) -> caza
* helicopter (38)      -> village (or the caza when the report names no village)
* anything that cannot be mapped to an HDX code -> ``unknown`` (``area_code`` NULL)

Unit names are mapped to HDX codes through ``canonicalize_caza`` and the explicit
tables in ``app/analytics/constants.py``, never by comparing names to names.
A breach is dated by its ``window_start`` (Beirut local date).

The national breach total per condition must equal ``count_breaches_by_condition``
over the same reports: ``assert_breach_parity`` checks it.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.analytics.constants import CAZA_NAME_TO_CODE, MOHAFAZA_NAME_TO_CODE
from app.news.constants.air_violation_conditions import AIR_VIOLATION_CONDITION_IDS
from app.news.dtos import AirViolationListParams
from app.news.repositories.air_violation_repository import AirViolationRepository
from app.news.services.air_violations.breach_counting_service import (
    UNIT_CAZA,
    UNIT_MOHAFAZA,
    UNIT_VILLAGE,
    AirViolationBreach,
    BreachReport,
    compute_breaches,
    count_breaches_by_condition,
)
from app.news.services.air_violations.caza_alias_resolver import canonicalize_caza

logger = logging.getLogger(__name__)

AIR_FAMILY_CODE = "air_violations"
UNKNOWN_LEVEL = "unknown"


@dataclass(frozen=True)
class AreaIndex:
    """HDX lookups needed to place a breach."""

    mohafaza_of_caza: dict[str, str | None]
    area_code_of_village: dict[int, str | None]
    area_info: dict[str, tuple[str, str | None, str | None]]  # code -> (level, caza, mohafaza)
    family_of_condition: dict[int, int]
    air_family_id: int | None


def load_area_index(db: Session) -> AreaIndex:
    area_info = {
        row.code: (row.level, row.caza_code, row.mohafaza_code)
        for row in db.execute(text("SELECT code, level, caza_code, mohafaza_code FROM admin_areas"))
    }
    mohafaza_of_caza = {
        code: info[2] for code, info in area_info.items() if info[0] == "caza"
    }
    village_codes = {
        int(row.id): row.admin_area_code
        for row in db.execute(text("SELECT id, admin_area_code FROM villages"))
    }
    families = {
        int(row.condition_id): int(row.family_id)
        for row in db.execute(text("SELECT condition_id, family_id FROM condition_families"))
    }
    air_family = db.execute(
        text("SELECT id FROM action_families WHERE code = :code"), {"code": AIR_FAMILY_CODE}
    ).scalar()
    return AreaIndex(mohafaza_of_caza, village_codes, area_info, families, air_family)


@dataclass(frozen=True)
class Attribution:
    unit_level: str
    area_code: str | None
    mohafaza_code: str | None
    caza_code: str | None


UNKNOWN = Attribution(UNKNOWN_LEVEL, None, None, None)


def attribute_breach(breach: AirViolationBreach, index: AreaIndex) -> Attribution:
    """Place one breach at its counting unit; ``UNKNOWN`` when it has no HDX code."""
    if breach.needs_review or breach.unit_type not in (UNIT_MOHAFAZA, UNIT_CAZA, UNIT_VILLAGE):
        return UNKNOWN
    if breach.unit_type == UNIT_MOHAFAZA:
        code = MOHAFAZA_NAME_TO_CODE.get(breach.unit_key)
        return Attribution(UNIT_MOHAFAZA, code, code, None) if code else UNKNOWN
    if breach.unit_type == UNIT_CAZA:
        caza = canonicalize_caza(breach.unit_key) or breach.unit_key
        code = CAZA_NAME_TO_CODE.get(caza)
        if not code or code not in index.area_info:
            return UNKNOWN
        return Attribution(UNIT_CAZA, code, index.mohafaza_of_caza.get(code), code)
    village_id = _village_id(breach)
    code = index.area_code_of_village.get(village_id) if village_id is not None else None
    if not code or code not in index.area_info:
        return UNKNOWN
    _level, caza_code, mohafaza_code = index.area_info[code]
    return Attribution(UNIT_VILLAGE, code, mohafaza_code, caza_code)


def _village_id(breach: AirViolationBreach) -> int | None:
    key = breach.unit_key or ""
    if key.startswith("id:"):
        try:
            return int(key[3:])
        except ValueError:
            return None
    return None


def load_breach_reports(
    db: Session, date_from: date | None = None, date_to: date | None = None
) -> list[BreachReport]:
    """Rows selected exactly as the Air Violations page selects them."""
    repository = AirViolationRepository(db)
    params = AirViolationListParams(event_date_from=date_from, event_date_to=date_to)
    items = repository._load_items(params, supported_only=True)  # same query + village labels as the page
    return [
        repository._breach_report(item)
        for item in items
        if int(item["condition_id"]) in AIR_VIOLATION_CONDITION_IDS
    ]


def compute_all_breaches(db: Session) -> list[AirViolationBreach]:
    return compute_breaches(load_breach_reports(db))


def aggregate_breaches(
    breaches: Iterable[AirViolationBreach], index: AreaIndex, *, only_from: date | None = None
) -> list[dict]:
    """Group breaches into fact rows (one per date x condition x unit)."""
    grouped: dict[tuple, dict] = {}
    for breach in breaches:
        breach_date = breach.window_start.date()
        if only_from is not None and breach_date < only_from:
            continue
        place = attribute_breach(breach, index)
        key = (breach_date, breach.condition_id, place.unit_level, place.area_code)
        row = grouped.get(key)
        if row is None:
            family_id = index.family_of_condition.get(breach.condition_id, index.air_family_id)
            if family_id is None:
                raise RuntimeError("action family 'air_violations' is missing; load reference data first")
            row = grouped[key] = {
                "breach_date": breach_date, "condition_id": breach.condition_id,
                "family_id": family_id, "unit_level": place.unit_level, "area_code": place.area_code,
                "mohafaza_code": place.mohafaza_code, "caza_code": place.caza_code,
                "breaches": 0, "reports": 0, "needs_review_breaches": 0,
            }
        row["breaches"] += 1
        row["reports"] += len(breach.report_ids)
        row["needs_review_breaches"] += 1 if breach.needs_review else 0
    return list(grouped.values())


_INSERT = text("""
INSERT INTO analytics_air_breach_facts
    (breach_date, condition_id, family_id, unit_level, area_code, mohafaza_code, caza_code,
     breaches, reports, needs_review_breaches, refreshed_at)
VALUES (:breach_date, :condition_id, :family_id, :unit_level, :area_code, :mohafaza_code, :caza_code,
        :breaches, :reports, :needs_review_breaches, now())
""")


def rebuild_air_facts(db: Session, *, from_date: date | None = None) -> dict:
    """Recompute breaches over every report and rewrite facts dated ``>= from_date``.

    Counting is global on purpose: anchored windows chain forward, so an edit can
    move later windows. Rewriting from ``from_date`` forward keeps the facts equal
    to what the Air Violations page would count. ``from_date=None`` rewrites all.
    """
    index = load_area_index(db)
    breaches = compute_all_breaches(db)
    rows = aggregate_breaches(breaches, index, only_from=from_date)
    if from_date is None:
        db.execute(text("DELETE FROM analytics_air_breach_facts"))
    else:
        db.execute(
            text("DELETE FROM analytics_air_breach_facts WHERE breach_date >= :d"), {"d": from_date}
        )
    if rows:
        db.execute(_INSERT, rows)
    if from_date is None:
        assert_breach_parity(db, breaches)
    return {"breaches": len(breaches), "fact_rows": len(rows)}


def fact_breach_totals(db: Session) -> dict[int, int]:
    return {
        int(row.condition_id): int(row.total)
        for row in db.execute(text(
            "SELECT condition_id, sum(breaches) AS total FROM analytics_air_breach_facts GROUP BY condition_id"
        ))
    }


def assert_breach_parity(db: Session, breaches: Iterable[AirViolationBreach]) -> None:
    """National breaches in the facts must equal ``count_breaches_by_condition``."""
    expected = {cid: n for cid, n in count_breaches_by_condition(breaches).items() if n}
    actual = {cid: n for cid, n in fact_breach_totals(db).items() if n}
    if expected != actual:
        raise AssertionError(f"air breach facts differ from count_breaches_by_condition: facts={actual} expected={expected}")


def affected_from_date(dates: Iterable[date]) -> date:
    """Earliest date whose facts a change on ``dates`` can move."""
    return min(dates) - timedelta(days=1)
