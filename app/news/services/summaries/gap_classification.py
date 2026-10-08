"""Why a summary item has no matching incident, and whether creating one is safe.

The buckets are the ones the summary-vs-news audit reports. Only NEWS_NEVER_ARRIVED may
lead to an incident created from a summary; every other bucket is a human-review item.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, text

from app.news.models import Condition, Incident, MessageStatus, RawMessage, Village
from app.news.models.summary_bulletin import SummaryBulletin, SummaryItem

from .condition_families import ConditionFamilies
from .normalize import normalize_token

BEIRUT = ZoneInfo("Asia/Beirut")
NEVER_ARRIVED = "NEWS_NEVER_ARRIVED"
FAILED = "NEWS_FAILED"
REJECTED = "NEWS_REJECTED"
WRONG_VILLAGE = "NEWS_WRONG_VILLAGE"
OTHER_ACTION = "SAME_VILLAGE_OTHER_ACTION"
_FAILED_STATUSES = {MessageStatus.pending, MessageStatus.error, MessageStatus.held_for_review}


@dataclass(frozen=True)
class Gap:
    bucket: str
    raw_ids: tuple[int, ...] = ()
    incident_ids: tuple[str, ...] = ()
    detail: str = ""


def _local(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(BEIRUT)


def _incident_local(incident: Incident) -> datetime:
    return datetime.combine(incident.event_date, incident.event_time or time(0, 0))


def incidents_in_window(session, summary: SummaryBulletin, *, tolerance_minutes: int) -> list[Incident]:
    """Visible, non-rejected incidents inside the tolerant summary window (date-only ones by day)."""
    tolerance = timedelta(minutes=tolerance_minutes)
    lower = _local(summary.window_start - tolerance).replace(tzinfo=None)
    upper = _local(summary.window_end + tolerance).replace(tzinfo=None)
    rows = session.scalars(select(Incident).where(
        Incident.is_deleted.is_(False),
        Incident.verification_status.is_distinct_from("rejected"),
        Incident.event_date >= lower.date(),
        Incident.event_date <= upper.date(),
    )).all()
    return [row for row in rows if (lower.date() <= row.event_date <= upper.date() if row.event_time is None else lower <= _incident_local(row) <= upper)]


def nearby_village_incidents(session, village_id: int, day: date, *, days: int = 1) -> list[Incident]:
    """Every non-deleted incident at the village within +-days of the day, whatever its condition."""
    return list(session.scalars(select(Incident).where(
        Incident.village_id == village_id,
        Incident.is_deleted.is_(False),
        Incident.event_date >= day - timedelta(days=days),
        Incident.event_date <= day + timedelta(days=days),
    ).order_by(Incident.event_date, Incident.created_at)))


def same_day_family_matches(session, item: SummaryItem, families: ConditionFamilies, day: date) -> list[Incident]:
    """Same village + same action family + same local calendar date, whatever the window was."""
    villages = [v for v in (item.primary_village_id, item.secondary_village_id) if v is not None]
    if not villages or item.condition_id is None:
        return []
    rows = session.scalars(select(Incident).where(
        Incident.village_id.in_(villages),
        Incident.condition_id.in_(sorted(families.equivalents(item.condition_id))),
        Incident.is_deleted.is_(False),
        Incident.verification_status.is_distinct_from("rejected"),
        Incident.event_date == day,
    )).all()
    return sorted(rows, key=lambda row: (_incident_local(row), row.created_at or datetime.min.replace(tzinfo=timezone.utc)))


class GapClassifier:
    def __init__(self, session, *, summary_message_ids: set[int], tolerance_minutes: int):
        self.session = session
        self.summary_message_ids = summary_message_ids
        self.tolerance_minutes = tolerance_minutes
        self._aliases = self._load_aliases()
        self._village_names = dict(session.execute(select(Village.id, Village.ref_name_ar)).all())
        self._condition_names = dict(session.execute(select(Condition.id, Condition.action_ar)).all())
        self._cache: dict[int, tuple[list[Incident], list[RawMessage]]] = {}

    def _load_aliases(self) -> dict[int, set[str]]:
        names: dict[int, set[str]] = {}
        for village_id, name in self.session.execute(select(Village.id, Village.ref_name_ar)):
            if name:
                names.setdefault(village_id, set()).add(normalize_token(name))
        for village_id, alias in self.session.execute(text("select village_id, alias_text from village_location_aliases where is_active")).all():
            if alias:
                names.setdefault(village_id, set()).add(normalize_token(alias))
        return names

    def _window_data(self, summary: SummaryBulletin) -> tuple[list[Incident], list[RawMessage]]:
        cached = self._cache.get(summary.id)
        if cached is None:
            incidents = incidents_in_window(self.session, summary, tolerance_minutes=self.tolerance_minutes)
            news = [raw for raw in self.session.scalars(select(RawMessage).where(
                RawMessage.raw_text.is_not(None),
                RawMessage.message_datetime >= summary.window_start,
                RawMessage.message_datetime <= summary.window_end,
            ).order_by(RawMessage.message_datetime, RawMessage.id))
                if raw.id not in self.summary_message_ids and raw.status != MessageStatus.summary_handled]
            cached = self._cache[summary.id] = (incidents, news)
        return cached

    def forget(self, summary_id: int) -> None:
        self._cache.pop(summary_id, None)

    def classify(self, summary: SummaryBulletin, item: SummaryItem, families: ConditionFamilies) -> Gap:
        """Call only for an item the window matcher could not match."""
        incidents, news = self._window_data(summary)
        villages = {v for v in (item.primary_village_id, item.secondary_village_id) if v is not None}
        same_village = [row for row in incidents if row.village_id in villages]
        if same_village:
            names = "; ".join(sorted({self._condition_names.get(row.condition_id, str(row.condition_id)) for row in same_village}))
            return Gap(OTHER_ACTION, incident_ids=tuple(str(row.id) for row in same_village), detail=names)
        aliases = self._aliases.get(item.primary_village_id, set())
        candidates = [raw for raw in news if any(alias and alias in normalize_token(raw.raw_text or "") for alias in aliases)]
        rejected = [raw for raw in candidates if raw.status == MessageStatus.rejected]
        failed = [raw for raw in candidates if raw.status in _FAILED_STATUSES]
        candidate_ids = {raw.id for raw in candidates}
        wrong = [row for row in incidents if row.raw_message_id in candidate_ids and row.village_id not in villages]
        if rejected:
            return Gap(REJECTED, raw_ids=tuple(raw.id for raw in rejected))
        if failed:
            return Gap(FAILED, raw_ids=tuple(raw.id for raw in failed))
        if wrong:
            return Gap(WRONG_VILLAGE, raw_ids=tuple(row.raw_message_id for row in wrong if row.raw_message_id),
                incident_ids=tuple(str(row.id) for row in wrong),
                detail="; ".join(sorted({str(self._village_names.get(row.village_id, row.village_id)) for row in wrong})))
        return Gap(NEVER_ARRIVED)
