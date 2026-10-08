"""Reconcile a parsed summary bulletin against the incidents of its window.

For every resolved item: link a live incident that already reports the event
(and leave one confirmation note on it), or create a casualty-free incident.
Problems collect in the bulletin's single review task. The caller owns the
transaction; nothing here commits.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.core.config import settings
from app.news.models import Condition, Incident, IncidentOrigin, Village
from app.news.models.summary_bulletin import (
    SummaryBulletin,
    SummaryItem,
    SummaryKind,
    SummaryModifier,
    SummaryReconciliationStatus,
    SummaryResolution,
    SummaryReviewStatus,
    SummaryReviewTask,
    SummaryStatus,
)

from .condition_families import ConditionFamilies, load_condition_families
from .decision_reasons import note as decision_note
from .gap_classification import (
    NEVER_ARRIVED,
    GapClassifier,
    nearby_village_incidents,
    same_day_family_matches,
)
from .normalize import normalize_token

logger = logging.getLogger(__name__)

BEIRUT = ZoneInfo("Asia/Beirut")
CASUALTY_REASON = "casualty_in_summary"
_CASUALTY_WORDS = re.compile(
    r"(?<![؀-ۿ])(?:ال)?(?:شهيد\S*|شهداء|استشه\S*|جريح\S*|جرح\S*|مجروح\S*|اصاب\S*|مصاب\S*|قتيل\S*|قتلي|قتلى|قتل)"
    r"(?![؀-ۿ])"
)


@dataclass
class StrictContext:
    """Backfill-only rules: create only for NEWS_NEVER_ARRIVED, guard duplicates, route the rest to review.

    ``events`` records every decision (for decisions.csv) and ``changes`` counts real writes, so a second
    apply can be proven to change nothing.
    """

    summary_message_ids: set[int]
    events: list[dict] = field(default_factory=list)
    failed_raw_ids: dict[int, set[int]] = field(default_factory=dict)
    changes: dict[str, int] = field(default_factory=dict)
    classifier: GapClassifier | None = None

    def count(self, key: str, amount: int = 1) -> None:
        self.changes[key] = self.changes.get(key, 0) + amount


@dataclass
class ItemOutcome:
    item_id: int
    position: int
    outcome: str  # matched | created | would_create | review | skipped
    incident_id: str | None = None
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "position": self.position,
            "outcome": self.outcome,
            "incident_id": self.incident_id,
            "reason": self.reason,
        }


@dataclass
class ReconcileResult:
    summary_id: int
    outcome: str  # reconciled | needs_review | skipped_locked | skipped_not_canonical | skipped_state
    dry_run: bool = False
    items: list[ItemOutcome] = field(default_factory=list)
    hidden: bool = False

    @property
    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.items:
            counts[item.outcome] = counts.get(item.outcome, 0) + 1
        return counts


def has_casualty_words(*texts: str | None) -> bool:
    return any(_CASUALTY_WORDS.search(normalize_token(text)) for text in texts if text)


def _local(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(BEIRUT)


def window_midpoint(start: datetime, end: datetime) -> datetime:
    """Midpoint of the window, clamped into it (guards inverted/degenerate windows)."""
    if end < start:
        start, end = end, start
    return min(max(start + (end - start) / 2, start), end)


def _incident_local_datetime(incident: Incident) -> datetime:
    return datetime.combine(incident.event_date, incident.event_time or time(0, 0))


def _confirmation_note(summary: SummaryBulletin) -> str:
    anchor = _local(summary.window_end or summary.created_at).date().isoformat()
    return f"مؤكد في ملخص {summary.channel or 'غير معروف'} بتاريخ {anchor}"


def _append_note(existing: str | None, text: str) -> str:
    if not existing:
        return text
    if text in existing:
        return existing
    return f"{existing}\n\n{text}"


def find_matching_incidents(
    session,
    item: SummaryItem,
    summary: SummaryBulletin,
    families: ConditionFamilies,
    *,
    tolerance_minutes: int,
) -> list[Incident]:
    """Live-or-summary incidents on the item's village(s) inside the tolerant window, earliest first."""
    villages = [v for v in (item.primary_village_id, item.secondary_village_id) if v is not None]
    if not villages or item.condition_id is None or summary.window_start is None or summary.window_end is None:
        return []
    tolerance = timedelta(minutes=tolerance_minutes)
    lower = _local(summary.window_start - tolerance).replace(tzinfo=None)
    upper = _local(summary.window_end + tolerance).replace(tzinfo=None)
    rows = session.scalars(
        select(Incident).where(
            Incident.village_id.in_(villages),
            Incident.condition_id.in_(sorted(families.equivalents(item.condition_id))),
            Incident.is_deleted.is_(False),
            Incident.verification_status.is_distinct_from("rejected"),
            Incident.event_date >= lower.date(),
            Incident.event_date <= upper.date(),
        )
    ).all()
    matches = []
    for incident in rows:
        if incident.event_time is None:
            # Date-only incident: it matches when its day overlaps the window days.
            fits = lower.date() <= incident.event_date <= upper.date()
        else:
            fits = lower <= _incident_local_datetime(incident) <= upper
        if fits:
            matches.append(incident)
    matches.sort(key=lambda i: (_incident_local_datetime(i), i.created_at or datetime.min.replace(tzinfo=timezone.utc)))
    return matches


def _created_note(summary: SummaryBulletin, item: SummaryItem) -> str:
    start = _local(summary.window_start).strftime("%Y-%m-%d %H:%M")
    end = _local(summary.window_end).strftime("%Y-%m-%d %H:%M")
    lines = [
        f"أُنشئ من ملخص {summary.channel or 'غير معروف'} (نافذة الملخص: {start} → {end})",
        f"النص: «{item.evidence_span}»",
    ]
    if item.modifier == SummaryModifier.between:
        lines.append(f"الموقع الكامل: {item.location_text}")
    if item.reported_count and item.reported_count > 1:
        lines.append(f"(×{item.reported_count} حسب الملخص)")
    return "\n".join(lines)


def _review_reasons_for(item: SummaryItem) -> list[dict[str, Any]]:
    return [{"type": CASUALTY_REASON, "item_ids": [item.id], "text": item.evidence_span}]


def _merge_task_reasons(task: SummaryReviewTask, new_reasons: list[dict[str, Any]]) -> int:
    existing = {(r.get("type"), tuple(r.get("item_ids") or [])) for r in (task.reasons or [])}
    merged = list(task.reasons or [])
    added = 0
    for reason in new_reasons:
        if (reason["type"], tuple(reason["item_ids"])) not in existing:
            merged.append(reason)
            added += 1
    if added:
        task.reasons = merged  # reassign: JSONB columns do not track in-place mutation
    return added


async def reconcile_summary(session, summary_id: int, *, dry_run: bool, strict: StrictContext | None = None) -> ReconcileResult:
    """Reconcile one summary in the caller's transaction (never commits).

    A concurrent worker holding the row makes this return ``skipped_locked``.
    With ``dry_run=True`` only ``summary_bulletins.shadow_result`` is written.
    """
    summary = session.scalar(
        select(SummaryBulletin).where(SummaryBulletin.id == summary_id).with_for_update(skip_locked=True)
    )
    if summary is None:
        return ReconcileResult(summary_id, "skipped_locked", dry_run)
    if summary.canonical_summary_id is not None or summary.status in {
        SummaryStatus.failed,
        SummaryStatus.skipped_repost,
    }:
        return ReconcileResult(summary_id, "skipped_not_canonical", dry_run)
    if summary.window_start is None or summary.window_end is None:
        return ReconcileResult(summary_id, "skipped_state", dry_run)

    families = load_condition_families(session)
    items = session.scalars(
        select(SummaryItem).where(SummaryItem.summary_id == summary.id).order_by(SummaryItem.position, SummaryItem.id)
    ).all()
    task = session.scalar(select(SummaryReviewTask).where(SummaryReviewTask.summary_id == summary.id))

    result = ReconcileResult(summary_id, "reconciled", dry_run)
    casualty_items: list[SummaryItem] = []
    to_create: list[SummaryItem] = []
    extra_reasons: list[dict[str, Any]] = []
    invalid_window = strict is not None and window_is_invalid(summary)
    if strict is not None and strict.classifier is not None:
        strict.classifier.forget(summary.id)

    # Pass 1: classify each pending, resolved item (reads only).
    for item in items:
        if item.resolution != SummaryResolution.resolved:
            continue  # already in the review task from intake
        if item.reconciliation_status != SummaryReconciliationStatus.pending:
            result.items.append(
                ItemOutcome(item.id, item.position, item.reconciliation_status.value, _incident_ref(item), "already_reconciled")
            )
            continue
        if item.primary_village_id is None or item.condition_id is None:
            result.items.append(ItemOutcome(item.id, item.position, "skipped", reason="incomplete_item"))
            continue
        if invalid_window:
            extra_reasons.append(_strict_reason("invalid_window", item, detail=f"{summary.window_start.isoformat()} -> {summary.window_end.isoformat()}"))
            result.items.append(ItemOutcome(item.id, item.position, "review", reason="invalid_window"))
            _record(strict, summary, item, "review", "invalid_window")
            continue
        if has_casualty_words(item.header_text, item.evidence_span, item.location_text):
            casualty_items.append(item)
            result.items.append(ItemOutcome(item.id, item.position, "review", reason=CASUALTY_REASON))
            continue
        matches = find_matching_incidents(
            session, item, summary, families, tolerance_minutes=settings.summary_match_tolerance_minutes
        )
        if not matches and strict is not None:
            matches = same_day_family_matches(session, item, families, _local(window_midpoint(summary.window_start, summary.window_end)).date())
        if matches:
            incident = matches[0]
            result.items.append(ItemOutcome(item.id, item.position, "matched", str(incident.id)))
            _record(strict, summary, item, "matched", incident_id=str(incident.id))
            if not dry_run:
                item.matched_incident_id = incident.id
                item.reconciliation_status = SummaryReconciliationStatus.matched
                new_note = _append_note(incident.note, _confirmation_note(summary))
                if strict is not None:
                    strict.count("item_matched")
                    if new_note != incident.note:
                        strict.count("confirmation_note")
                incident.note = new_note
                session.add(incident)
        elif strict is not None:
            gap = strict.classifier.classify(summary, item, families)
            day = _local(window_midpoint(summary.window_start, summary.window_end)).date()
            blockers = nearby_village_incidents(session, item.primary_village_id, day) if gap.bucket == NEVER_ARRIVED else []
            if gap.bucket != NEVER_ARRIVED:
                extra_reasons.append(_strict_reason(gap.bucket.lower(), item, raw_ids=gap.raw_ids, incident_ids=gap.incident_ids, detail=gap.detail))
                result.items.append(ItemOutcome(item.id, item.position, "review", reason=gap.bucket.lower()))
                _record(strict, summary, item, "review", gap.bucket, raw_ids=gap.raw_ids, incident_ids=gap.incident_ids)
                if gap.bucket == "NEWS_FAILED":
                    strict.failed_raw_ids.setdefault(summary.raw_message_id, set()).update(gap.raw_ids)
            elif blockers:
                ids = tuple(str(row.id) for row in blockers)
                extra_reasons.append(_strict_reason("nearby_incident_guard", item, incident_ids=ids))
                result.items.append(ItemOutcome(item.id, item.position, "review", reason="nearby_incident_guard"))
                _record(strict, summary, item, "review", "NEARBY_INCIDENT_GUARD", incident_ids=ids)
            else:
                to_create.append(item)
                result.items.append(ItemOutcome(item.id, item.position, "would_create"))
        else:
            to_create.append(item)
            result.items.append(ItemOutcome(item.id, item.position, "would_create"))

    # Pass 2: create the missing ones (writes) unless dry-run.
    outcome_by_item = {o.item_id: o for o in result.items}
    if to_create and not dry_run:
        created_by_item = _create_incidents(session, summary, to_create, strict=strict)
        for item in to_create:
            outcome = outcome_by_item[item.id]
            incident = created_by_item.get(item.id)
            if incident is None:
                outcome.outcome, outcome.reason = "skipped", "create_failed"
                continue
            item.created_incident_id = incident.id
            item.reconciliation_status = SummaryReconciliationStatus.created
            outcome.outcome, outcome.incident_id = "created", str(incident.id)
            if strict is not None:
                strict.count("incident_created")
                _record(strict, summary, item, "created", "NEWS_NEVER_ARRIVED", incident_id=str(incident.id))

    # Review task: casualty and (strict) bucket items join the single task per summary.
    review_present = bool(casualty_items or extra_reasons)
    if review_present and not dry_run:
        reasons = [r for item in casualty_items for r in _review_reasons_for(item)] + extra_reasons
        if task is None:
            task = SummaryReviewTask(summary_id=summary.id, reasons=reasons, status=SummaryReviewStatus.open)
            session.add(task)
            if strict is not None:
                strict.count("review_task_created")
                strict.count("review_reason_added", len(reasons))
        elif task.status == SummaryReviewStatus.open:
            added = _merge_task_reasons(task, reasons)
            if strict is not None and added:
                strict.count("review_reason_added", added)
        else:
            known = {(r.get("type"), tuple(r.get("item_ids") or [])) for r in (task.reasons or [])}
            fresh = [r for r in reasons if (r["type"], tuple(r["item_ids"])) not in known]
            if fresh:
                task.reasons, task.status = list(task.reasons or []) + fresh, SummaryReviewStatus.open
                task.resolved_by, task.resolved_at = None, None
                if strict is not None:
                    strict.count("review_reason_added", len(fresh))

    task_open = (task is not None and task.status == SummaryReviewStatus.open) or (
        dry_run and review_present
    )
    resolved_items = [i for i in items if i.resolution == SummaryResolution.resolved]
    all_matched = (
        bool(resolved_items)
        and len(result.items) == len(resolved_items)
        and all(o.outcome == "matched" for o in result.items)
    )
    result.hidden = all_matched and not task_open
    result.outcome = "needs_review" if task_open else "reconciled"

    payload = {
        "dry_run": dry_run,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "window": {"start": summary.window_start.isoformat(), "end": summary.window_end.isoformat(), "basis": summary.window_basis},
        "items": [o.as_dict() for o in result.items],
        "counts": result.counts,
        "would_hide": result.hidden,
        "review_task_open": task_open,
    }
    if dry_run:
        summary.shadow_result = payload
    else:
        new_status = SummaryStatus.needs_review if task_open else SummaryStatus.reconciled
        if strict is not None and (summary.hidden, summary.status, summary.last_error) != (result.hidden, new_status, None):
            strict.count("summary_state")
        summary.hidden = result.hidden
        summary.status = new_status
        summary.last_error = None
    session.add(summary)
    session.flush()
    return result


def window_is_invalid(summary: SummaryBulletin) -> bool:
    """Zero/negative window, or a full-day summary shorter than three hours."""
    from .window import MIN_DAILY_WINDOW

    length = summary.window_end - summary.window_start
    return length <= timedelta(0) or (summary.kind == SummaryKind.full_day and length < MIN_DAILY_WINDOW)


def _strict_reason(kind: str, item: SummaryItem, *, raw_ids=(), incident_ids=(), detail: str = "") -> dict[str, Any]:
    reason: dict[str, Any] = {"type": kind, "item_ids": [item.id], "text": item.evidence_span}
    if raw_ids:
        reason["raw_message_ids"] = [int(value) for value in raw_ids]
    if incident_ids:
        reason["incident_ids"] = list(incident_ids)
    if detail:
        reason["detail"] = detail
    return reason


def _record(strict: StrictContext | None, summary: SummaryBulletin, item: SummaryItem, outcome: str, reason: str = "", *, raw_ids=(), incident_ids=(), incident_id: str | None = None) -> None:
    if strict is None:
        return
    strict.events.append({
        "summary_raw_message_id": summary.raw_message_id, "item_position": item.position, "village_id": item.primary_village_id,
        "condition_id": item.condition_id, "outcome": outcome, "reason": reason,
        "raw_message_ids": ";".join(str(v) for v in raw_ids), "incident_ids": ";".join(incident_ids) if incident_ids else (incident_id or ""),
    })


def _incident_ref(item: SummaryItem) -> str | None:
    incident_id = item.matched_incident_id or item.created_incident_id
    return str(incident_id) if incident_id else None


def _create_incidents(session, summary: SummaryBulletin, items: list[SummaryItem], *, strict: StrictContext | None = None) -> dict[int, Incident]:
    from app.news.services.materialization.incident_materialization_service import (
        IncidentMaterializationService,
    )

    service = IncidentMaterializationService(session)
    condition_ar = dict(session.execute(select(Condition.id, Condition.action_ar)).all())
    village_ar = dict(
        session.execute(
            select(Village.id, Village.ref_name_ar).where(Village.id.in_({i.primary_village_id for i in items}))
        ).all()
    )
    midpoint = _local(window_midpoint(summary.window_start, summary.window_end))
    created: dict[int, Incident] = {}
    for item in items:
        label = condition_ar.get(item.condition_id) or item.header_text or ""
        place = village_ar.get(item.primary_village_id) or item.location_text
        incident = service.create_summary_incident(
            village_id=item.primary_village_id,
            condition_id=item.condition_id,
            event_datetime=midpoint,
            khabar=f"{label}: {place} (من ملخص {summary.channel or ''})".strip(),
            note=_created_note(summary, item),
            source_id=summary.source_id,
            source_summary_item_id=item.id,
            hash_suffix=f"summary:{summary.id}:{item.id}",
        )
        if incident is not None:
            created[item.id] = incident
            if strict is not None:
                _stamp_created(incident, summary, item)
    return created


def _stamp_created(incident: Incident, summary: SummaryBulletin, item: SummaryItem) -> None:
    if incident.decision_reason:
        return
    incident.decision_reason = "ACCEPTED_MISSED_NEVER_ARRIVED"
    incident.decision_source_summary_id = summary.id
    incident.decided_at = datetime.now(timezone.utc)
    incident.note = _append_note(incident.note, decision_note(
        "ACCEPTED_MISSED_NEVER_ARRIVED", summary_channel=summary.channel or "",
        summary_date=_local(summary.window_end or summary.created_at).date().isoformat(), evidence_span=item.evidence_span,
    ))
