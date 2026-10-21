"""CNRS breach counting for air violations (pure: dataclasses in, dataclasses out).

Storage keeps one ``air_violations`` row per report. A *breach* is the counting
unit the CNRS methodology defines, computed at read time from those rows:

* Warplane (35): per mohafaza, anchored 10-minute windows. A report naming
  several mohafazat contributes to each of them.
* Drone / surveillance (36): per caza. Listed cazas use anchored 6-hour
  windows; every other caza counts once per Beirut calendar day.
* Helicopter (38): every report counts once per village it names.
* Spy balloon (34): every report counts once per caza it names.

Anchored window: the first report of a unit opens the window; reports of the
same condition and unit with ``event_datetime - anchor <= window`` join it; the
first one past that opens a new window.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Iterable, Sequence

from app.core.config import settings
from app.core.text_normalization import normalize_arabic_text
from app.news.constants.air_violation_conditions import (
    AIR_VIOLATION_DRONE_CONDITION_ID,
    AIR_VIOLATION_HELICOPTER_CONDITION_ID,
    AIR_VIOLATION_SPY_BALLOON_CONDITION_ID,
    AIR_VIOLATION_WARPLANE_CONDITION_ID,
    CAZA_TO_MOHAFAZA,
    DRONE_SIX_HOUR_CAZAS,
)
from app.news.services.air_violations.caza_alias_resolver import canonicalize_caza

UNIT_MOHAFAZA = "mohafaza"
UNIT_CAZA = "caza"
UNIT_VILLAGE = "village"
UNKNOWN_UNIT = "Unknown"
UNKNOWN_UNIT_AR = "غير معروف"
DAILY_WINDOW_MINUTES = 24 * 60


@dataclass(frozen=True)
class BreachVillage:
    village_id: int | None
    name: str
    caza_en: str | None = None
    caza_ar: str | None = None
    mohafaza_en: str | None = None
    mohafaza_ar: str | None = None


@dataclass(frozen=True)
class BreachReport:
    id: int
    condition_id: int
    event_date: date
    event_time: time | None
    caza_en: str | None = None
    caza_ar: str | None = None
    villages: tuple[BreachVillage, ...] = ()


@dataclass(frozen=True)
class AirViolationBreach:
    id: str
    condition_id: int
    unit_type: str
    unit_key: str
    unit_en: str
    unit_ar: str | None
    window_start: datetime
    window_end: datetime
    report_ids: tuple[int, ...]
    villages: tuple[BreachVillage, ...] = ()
    window_minutes: int | None = None
    # True when the unit could not be resolved (counted under "Unknown").
    needs_review: bool = False


@dataclass
class _Unit:
    unit_type: str
    key: str
    label_en: str
    label_ar: str | None
    villages: list[BreachVillage] = field(default_factory=list)
    needs_review: bool = False


def event_datetime(report: BreachReport) -> datetime:
    """NULL ``event_time`` counts as 00:00, matching how rows are stored."""
    return datetime.combine(report.event_date, report.event_time or time.min)


def _normalized_name(value: object) -> str:
    return " ".join(normalize_arabic_text(str(value or "")).casefold().split())


def _village_key(village: BreachVillage) -> str:
    if village.village_id is not None:
        return f"id:{village.village_id}"
    return f"name:{_normalized_name(village.name)}"


def _village_caza(village: BreachVillage) -> str | None:
    return canonicalize_caza(village.caza_en) or canonicalize_caza(village.caza_ar)


def _village_mohafaza(village: BreachVillage) -> tuple[str | None, str | None]:
    if village.mohafaza_en:
        return village.mohafaza_en, village.mohafaza_ar
    caza = _village_caza(village)
    return CAZA_TO_MOHAFAZA.get(caza or ""), None


def _unknown_unit(unit_type: str) -> _Unit:
    return _Unit(unit_type, UNKNOWN_UNIT, UNKNOWN_UNIT, UNKNOWN_UNIT_AR, needs_review=True)


def _row_caza_unit(report: BreachReport, unit_type: str = UNIT_CAZA) -> _Unit:
    caza = canonicalize_caza(report.caza_en) or canonicalize_caza(report.caza_ar)
    if not caza:
        return _unknown_unit(unit_type)
    return _Unit(unit_type, caza, caza, report.caza_ar)


def _caza_units(report: BreachReport) -> list[_Unit]:
    units: dict[str, _Unit] = {}
    for village in report.villages:
        caza = _village_caza(village)
        if not caza:
            continue
        unit = units.setdefault(caza, _Unit(UNIT_CAZA, caza, caza, village.caza_ar))
        unit.villages.append(village)
    return list(units.values()) or [_row_caza_unit(report)]


def _mohafaza_units(report: BreachReport) -> list[_Unit]:
    units: dict[str, _Unit] = {}
    for village in report.villages:
        mohafaza_en, mohafaza_ar = _village_mohafaza(village)
        if not mohafaza_en:
            continue
        unit = units.setdefault(
            mohafaza_en, _Unit(UNIT_MOHAFAZA, mohafaza_en, mohafaza_en, mohafaza_ar)
        )
        unit.villages.append(village)
    if units:
        return list(units.values())
    caza = canonicalize_caza(report.caza_en) or canonicalize_caza(report.caza_ar)
    mohafaza = CAZA_TO_MOHAFAZA.get(caza or "")
    if mohafaza:
        return [_Unit(UNIT_MOHAFAZA, mohafaza, mohafaza, None)]
    return [_unknown_unit(UNIT_MOHAFAZA)]


def _village_units(report: BreachReport) -> list[_Unit]:
    units: dict[str, _Unit] = {}
    for village in report.villages:
        key = _village_key(village)
        if key == "name:":
            continue
        units.setdefault(
            key, _Unit(UNIT_VILLAGE, key, village.name, None, [village])
        )
    return list(units.values()) or [_row_caza_unit(report)]


def expand_report_units(report: BreachReport) -> list[_Unit]:
    """The distinct counting units one report contributes to."""
    if report.condition_id == AIR_VIOLATION_WARPLANE_CONDITION_ID:
        return _mohafaza_units(report)
    if report.condition_id == AIR_VIOLATION_HELICOPTER_CONDITION_ID:
        return _village_units(report)
    if report.condition_id in (
        AIR_VIOLATION_DRONE_CONDITION_ID,
        AIR_VIOLATION_SPY_BALLOON_CONDITION_ID,
    ):
        return _caza_units(report)
    return []


def _warplane_window(window: timedelta | None) -> timedelta:
    return window or timedelta(minutes=settings.air_violation_warplane_window_minutes)


def _drone_long_window(window: timedelta | None) -> timedelta:
    return window or timedelta(hours=settings.air_violation_drone_long_window_hours)


def breach_window_minutes(
    condition_id: int,
    unit_key: str | None,
    *,
    warplane_window: timedelta | None = None,
    drone_long_window: timedelta | None = None,
) -> int | None:
    """Window length in minutes (1440 = daily); ``None`` when there is no window."""
    if condition_id == AIR_VIOLATION_WARPLANE_CONDITION_ID:
        return int(_warplane_window(warplane_window).total_seconds() // 60)
    if condition_id == AIR_VIOLATION_DRONE_CONDITION_ID:
        if unit_key in DRONE_SIX_HOUR_CAZAS:
            return int(_drone_long_window(drone_long_window).total_seconds() // 60)
        return DAILY_WINDOW_MINUTES
    return None


def _merge_villages(
    villages: Iterable[BreachVillage],
) -> tuple[BreachVillage, ...]:
    merged: dict[str, BreachVillage] = {}
    for village in villages:
        key = _village_key(village)
        if key != "name:":
            merged.setdefault(key, village)
    return tuple(merged.values())


def _build_breach(
    condition_id: int,
    unit: _Unit,
    members: Sequence[tuple[BreachReport, _Unit]],
    anchor: datetime,
    *,
    window_minutes: int | None,
    suffix: str = "",
) -> AirViolationBreach:
    ordered = sorted(members, key=lambda pair: (event_datetime(pair[0]), pair[0].id))
    return AirViolationBreach(
        id=f"{condition_id}:{unit.unit_type}:{unit.key}:{anchor.isoformat()}{suffix}",
        condition_id=condition_id,
        unit_type=unit.unit_type,
        unit_key=unit.key,
        unit_en=unit.label_en,
        unit_ar=unit.label_ar,
        window_start=anchor,
        window_end=max(event_datetime(report) for report, _ in ordered),
        report_ids=tuple(dict.fromkeys(report.id for report, _ in ordered)),
        villages=_merge_villages(
            village for _, member_unit in ordered for village in member_unit.villages
        ),
        window_minutes=window_minutes,
        needs_review=unit.needs_review,
    )


def _anchored_windows(
    pairs: list[tuple[BreachReport, _Unit]], length: timedelta
) -> list[list[tuple[BreachReport, _Unit]]]:
    groups: list[list[tuple[BreachReport, _Unit]]] = []
    anchor: datetime | None = None
    for pair in sorted(pairs, key=lambda p: (event_datetime(p[0]), p[0].id)):
        moment = event_datetime(pair[0])
        if anchor is None or moment - anchor > length:
            groups.append([pair])
            anchor = moment
        else:
            groups[-1].append(pair)
    return groups


def compute_breaches(
    reports: Iterable[BreachReport],
    *,
    warplane_window: timedelta | None = None,
    drone_long_window: timedelta | None = None,
) -> list[AirViolationBreach]:
    """Apply the CNRS counting rules to ``reports`` and return every breach."""
    warplane_length = _warplane_window(warplane_window)
    drone_length = _drone_long_window(drone_long_window)

    windowed: dict[tuple[int, str, str], list[tuple[BreachReport, _Unit]]] = {}
    daily: dict[tuple[str, date], list[tuple[BreachReport, _Unit]]] = {}
    breaches: list[AirViolationBreach] = []

    for report in reports:
        for unit in expand_report_units(report):
            condition_id = report.condition_id
            moment = event_datetime(report)
            if condition_id in (
                AIR_VIOLATION_HELICOPTER_CONDITION_ID,
                AIR_VIOLATION_SPY_BALLOON_CONDITION_ID,
            ):
                breaches.append(_build_breach(
                    condition_id, unit, [(report, unit)], moment,
                    window_minutes=None, suffix=f":{report.id}",
                ))
            elif condition_id == AIR_VIOLATION_DRONE_CONDITION_ID and unit.key not in DRONE_SIX_HOUR_CAZAS:
                daily.setdefault((unit.key, report.event_date), []).append((report, unit))
            else:
                windowed.setdefault(
                    (condition_id, unit.unit_type, unit.key), []
                ).append((report, unit))

    for (condition_id, _unit_type, unit_key), pairs in windowed.items():
        length = (
            warplane_length
            if condition_id == AIR_VIOLATION_WARPLANE_CONDITION_ID
            else drone_length
        )
        minutes = int(length.total_seconds() // 60)
        for group in _anchored_windows(pairs, length):
            anchor = min(event_datetime(report) for report, _ in group)
            breaches.append(_build_breach(
                condition_id, group[0][1], group, anchor, window_minutes=minutes,
            ))

    for (_caza, day), pairs in daily.items():
        breaches.append(_build_breach(
            AIR_VIOLATION_DRONE_CONDITION_ID, pairs[0][1], pairs,
            datetime.combine(day, time.min), window_minutes=DAILY_WINDOW_MINUTES,
        ))

    return sorted(breaches, key=lambda b: (b.window_start, b.id), reverse=True)


def count_breaches_by_condition(
    breaches: Iterable[AirViolationBreach],
) -> dict[int, int]:
    counts = {
        AIR_VIOLATION_SPY_BALLOON_CONDITION_ID: 0,
        AIR_VIOLATION_WARPLANE_CONDITION_ID: 0,
        AIR_VIOLATION_DRONE_CONDITION_ID: 0,
        AIR_VIOLATION_HELICOPTER_CONDITION_ID: 0,
    }
    for breach in breaches:
        counts[breach.condition_id] = counts.get(breach.condition_id, 0) + 1
    return counts
