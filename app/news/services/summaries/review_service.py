"""Admin read/write operations for summary bulletins and their single review task.

The reconcile worker owns incident writes; this module only (a) lists and describes
summaries, (b) turns a reviewer's decisions into item updates (marking them pending and
queueing the summary), and (c) records optional learning (village alias, header mapping).
Nothing here commits; the API layer does.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal, Sequence
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.news.models import Condition, RawMessage, Village
from app.news.models.summary_bulletin import (
    SummaryBulletin,
    SummaryHeaderMapping,
    SummaryItem,
    SummaryItemOrigin,
    SummaryModifier,
    SummaryReconciliationStatus,
    SummaryResolution,
    SummaryReviewStatus,
    SummaryReviewTask,
    SummaryStatus,
)
from app.news.models.village_location_alias import VillageLocationAlias

from .gazetteer import build_gazetteer_snapshot
from .header_store import header_dictionary_for_session
from .headers import HeaderDictionarySnapshot
from .lexicon import LEXICON
from .normalize import normalize_token
from .parser import parse_summary
from .reconcile_service import CASUALTY_REASON, _create_incidents

BEIRUT = ZoneInfo("Asia/Beirut")
REASON_TYPES = ("unresolved_location", "unknown_header", CASUALTY_REASON)


class ReviewError(Exception):
    """A request the reviewer can fix; ``status`` is the HTTP code the API should use."""

    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


class ReviewAction(BaseModel):
    """One reviewer decision for one item of the bulletin's review task."""

    item_id: int
    action: Literal["resolve", "dismiss", "create_incident"] = "resolve"
    # unresolved_location
    village_id: int | None = None
    save_alias: bool = False
    # unknown_header (also used by unresolved_location when the section's action is unknown)
    condition_ids: list[int] | None = None
    save_mapping: bool = False

    @model_validator(mode="after")
    def _non_empty_conditions(self) -> "ReviewAction":
        if self.condition_ids is not None and not self.condition_ids:
            raise ValueError("condition_ids must not be empty")
        return self


class ResolveRequest(BaseModel):
    actions: list[ReviewAction] = Field(min_length=1)


@dataclass
class ResolveOutcome:
    handled_item_ids: list[int]
    new_item_ids: list[int]
    task_status: str
    alias_saved: list[int]
    mapping_saved: list[str]


# ---------------------------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------------------------

def _local_day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=BEIRUT)
    return start, start + timedelta(days=1)


def _reason_state(task: SummaryReviewTask | None) -> dict[int, dict[str, Any]]:
    """item id -> its review reason (with ``handled`` info) for the task."""
    state: dict[int, dict[str, Any]] = {}
    for reason in (task.reasons if task is not None else None) or []:
        for item_id in reason.get("item_ids") or []:
            state[int(item_id)] = reason
    return state


def display_status(item: SummaryItem, reason: dict[str, Any] | None) -> str:
    if item.resolution == SummaryResolution.unknown_header:
        return "header_handled" if reason and reason.get("handled") else "unknown_header"
    if item.resolution == SummaryResolution.unresolved_location:
        return "unresolved"
    if reason and reason.get("type") == CASUALTY_REASON and not reason.get("handled") and item.reconciliation_status == SummaryReconciliationStatus.pending:
        return "casualty"
    if item.reconciliation_status == SummaryReconciliationStatus.ambiguous:
        return "dismissed"
    return item.reconciliation_status.value


def list_summaries(
    session: Session,
    *,
    status: str | None = None,
    channel: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    has_open_task: bool | None = None,
    include_hidden: bool = False,
    page: int = 1,
    page_size: int = 25,
) -> tuple[list[dict[str, Any]], int]:
    """Canonical summaries only (reposts are shown on their canonical's detail)."""
    filters = [SummaryBulletin.canonical_summary_id.is_(None), SummaryBulletin.status != SummaryStatus.skipped_repost]
    if not include_hidden:
        filters.append(SummaryBulletin.hidden.is_(False))
    if status:
        try:
            filters.append(SummaryBulletin.status == SummaryStatus(status))
        except ValueError as exc:
            raise ReviewError(f"Unknown status {status!r}.") from exc
    if channel:
        filters.append(SummaryBulletin.channel == channel)
    if date_from:
        filters.append(SummaryBulletin.window_end >= _local_day_bounds(date_from)[0])
    if date_to:
        filters.append(SummaryBulletin.window_end < _local_day_bounds(date_to)[1])
    open_task = exists().where(
        SummaryReviewTask.summary_id == SummaryBulletin.id, SummaryReviewTask.status == SummaryReviewStatus.open
    )
    if has_open_task is True:
        filters.append(open_task)
    elif has_open_task is False:
        filters.append(~open_task)
    total = session.scalar(select(func.count(SummaryBulletin.id)).where(*filters)) or 0
    summaries = session.scalars(
        select(SummaryBulletin)
        .where(*filters)
        .order_by(SummaryBulletin.window_end.desc().nulls_last(), SummaryBulletin.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return [_summary_row(session, summary) for summary in summaries], int(total)


def _summary_row(session: Session, summary: SummaryBulletin) -> dict[str, Any]:
    items = session.scalars(select(SummaryItem).where(SummaryItem.summary_id == summary.id)).all()
    task = session.scalar(select(SummaryReviewTask).where(SummaryReviewTask.summary_id == summary.id))
    reasons = _reason_state(task)
    chips: dict[str, int] = {}
    for reason in (task.reasons if task is not None else None) or []:
        if not reason.get("handled"):
            chips[reason["type"]] = chips.get(reason["type"], 0) + len(reason.get("item_ids") or [])
    return {
        "id": summary.id,
        "channel": summary.channel,
        "status": summary.status.value,
        "kind": summary.kind.value,
        "hidden": summary.hidden,
        "window_start": summary.window_start,
        "window_end": summary.window_end,
        "created_at": summary.created_at,
        "item_count": len(items),
        "unresolved_count": sum(1 for i in items if display_status(i, reasons.get(i.id)) in {"unresolved", "unknown_header", "casualty"}),
        "matched_count": sum(1 for i in items if i.reconciliation_status == SummaryReconciliationStatus.matched),
        "created_count": sum(1 for i in items if i.reconciliation_status == SummaryReconciliationStatus.created),
        "has_open_task": bool(task is not None and task.status == SummaryReviewStatus.open),
        "task_id": task.id if task is not None else None,
        "reasons": [{"type": key, "count": count} for key, count in chips.items()],
    }


def summary_detail(session: Session, summary_id: int) -> dict[str, Any] | None:
    summary = session.get(SummaryBulletin, summary_id)
    if summary is None:
        return None
    raw = session.get(RawMessage, summary.raw_message_id)
    items = session.scalars(
        select(SummaryItem).where(SummaryItem.summary_id == summary.id).order_by(SummaryItem.position, SummaryItem.id)
    ).all()
    task = session.scalar(select(SummaryReviewTask).where(SummaryReviewTask.summary_id == summary.id))
    reasons = _reason_state(task)
    villages = {
        v.id: v for v in session.scalars(
            select(Village).where(Village.id.in_({x for i in items for x in (i.primary_village_id, i.secondary_village_id) if x}))
        )
    } if items else {}
    conditions = {c.id: c for c in session.scalars(select(Condition))}
    reposts = session.scalars(
        select(SummaryBulletin).where(SummaryBulletin.canonical_summary_id == summary.id).order_by(SummaryBulletin.id)
    ).all()

    def village_view(village_id: int | None) -> dict[str, Any] | None:
        village = villages.get(village_id) if village_id else None
        if village is None:
            return None
        return {"id": village.id, "name_ar": village.ref_name_ar, "name_en": village.ref_name_en or village.cad_name, "caza_en": village.caza_en}

    def condition_view(condition_id: int | None) -> dict[str, Any] | None:
        condition = conditions.get(condition_id) if condition_id else None
        return {"id": condition.id, "name_en": condition.action_en, "name_ar": condition.action_ar} if condition else None

    return {
        **_summary_row(session, summary),
        "raw_message_id": summary.raw_message_id,
        "raw_text": raw.raw_text if raw is not None else None,
        "window_basis": summary.window_basis,
        "last_error": summary.last_error,
        "process_after": summary.process_after,
        "canonical_summary_id": summary.canonical_summary_id,
        "shadow_result": summary.shadow_result,
        "reposts": [{"id": r.id, "channel": r.channel, "created_at": r.created_at} for r in reposts],
        "items": [
            {
                "id": i.id,
                "position": i.position,
                "header_text": i.header_text,
                "condition": condition_view(i.condition_id),
                "location_text": i.location_text,
                "primary_village": village_view(i.primary_village_id),
                "secondary_village": village_view(i.secondary_village_id),
                "modifier": i.modifier.value,
                "reported_count": i.reported_count,
                "evidence_span": i.evidence_span,
                "origin": i.origin.value,
                "resolution": i.resolution.value,
                "reconciliation_status": i.reconciliation_status.value,
                "display_status": display_status(i, reasons.get(i.id)),
                "reason_type": (reasons.get(i.id) or {}).get("type"),
                "matched_incident_id": i.matched_incident_id,
                "created_incident_id": i.created_incident_id,
            }
            for i in items
        ],
        "review_task": None if task is None else {
            "id": task.id,
            "status": task.status.value,
            "reasons": task.reasons,
            "resolved_by": task.resolved_by,
            "resolved_at": task.resolved_at,
        },
    }


# ---------------------------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------------------------

def _open_task(session: Session, summary_id: int) -> tuple[SummaryBulletin, SummaryReviewTask]:
    summary = session.scalar(select(SummaryBulletin).where(SummaryBulletin.id == summary_id).with_for_update())
    if summary is None:
        raise ReviewError("Summary not found.", 404)
    task = session.scalar(select(SummaryReviewTask).where(SummaryReviewTask.summary_id == summary_id))
    if task is None or task.status != SummaryReviewStatus.open:
        raise ReviewError("This summary has no open review task.", 409)
    return summary, task


def _mark_handled(task: SummaryReviewTask, item_id: int, info: dict[str, Any]) -> None:
    updated = []
    for reason in task.reasons or []:
        if item_id in (reason.get("item_ids") or []) and not reason.get("handled"):
            reason = {**reason, "handled": info}
        updated.append(reason)
    task.reasons = updated  # reassign: JSONB does not track in-place mutation


def _all_handled(task: SummaryReviewTask) -> bool:
    return all(reason.get("handled") for reason in task.reasons or [])


def _close_if_done(task: SummaryReviewTask, user_id: UUID | None, status: SummaryReviewStatus) -> None:
    if _all_handled(task):
        task.status = status
        task.resolved_by = user_id
        task.resolved_at = datetime.now(timezone.utc)


def _queue(summary: SummaryBulletin, session: Session) -> None:
    """Make the worker pick the summary up again right away if anything is pending."""
    pending = session.scalar(
        select(func.count(SummaryItem.id)).where(
            SummaryItem.summary_id == summary.id,
            SummaryItem.resolution == SummaryResolution.resolved,
            SummaryItem.reconciliation_status == SummaryReconciliationStatus.pending,
        )
    )
    if pending:
        summary.process_after = datetime.now(timezone.utc)
        if summary.status in {SummaryStatus.needs_review, SummaryStatus.reconciled}:
            summary.status = SummaryStatus.parsed
            summary.hidden = False
            summary.attempts = 0


def _save_alias(session: Session, item: SummaryItem, village_id: int) -> bool:
    text = (item.location_text or "").strip()
    normalized = normalize_token(text)
    if not normalized:
        return False
    existing = session.scalar(select(VillageLocationAlias).where(VillageLocationAlias.alias_normalized == normalized))
    if existing is not None:
        return existing.village_id == village_id
    session.add(VillageLocationAlias(
        alias_text=text, alias_normalized=normalized, village_id=village_id,
        note="Learned from summary review", requires_geo_context=False, is_active=True,
    ))
    return True


def _save_mapping(session: Session, header_text: str, condition_ids: Sequence[int], user_id: UUID | None) -> bool:
    key = normalize_token(header_text)
    if not key:
        return False
    row = session.scalar(select(SummaryHeaderMapping).where(SummaryHeaderMapping.header_text_normalized == key))
    if row is None:
        session.add(SummaryHeaderMapping(header_text_normalized=key, condition_ids=list(condition_ids), created_by=user_id))
    else:
        row.condition_ids = list(condition_ids)
    return True


def _require_conditions(session: Session, condition_ids: Sequence[int]) -> list[int]:
    found = set(session.scalars(select(Condition.id).where(Condition.id.in_(condition_ids), Condition.is_active.is_(True))))
    missing = [c for c in condition_ids if c not in found]
    if missing:
        raise ReviewError(f"Unknown condition id(s): {missing}.")
    return list(dict.fromkeys(condition_ids))


def _next_position(session: Session, summary_id: int) -> int:
    return int(session.scalar(select(func.coalesce(func.max(SummaryItem.position), -1)).where(SummaryItem.summary_id == summary_id)) or -1) + 1


def _resolve_location(session: Session, summary: SummaryBulletin, item: SummaryItem, action: ReviewAction, out: ResolveOutcome) -> None:
    if action.village_id is None:
        raise ReviewError(f"Item {item.id}: village_id is required to resolve a location.")
    village = session.get(Village, action.village_id)
    if village is None or not village.is_active:
        raise ReviewError(f"Item {item.id}: village {action.village_id} does not exist.")
    condition_ids = _require_conditions(session, action.condition_ids) if action.condition_ids else (
        [item.condition_id] if item.condition_id else []
    )
    if not condition_ids:
        raise ReviewError(f"Item {item.id}: the section's action is unknown; choose condition_ids too.")
    item.primary_village_id = village.id
    item.condition_id = condition_ids[0]
    item.resolution = SummaryResolution.resolved
    item.reconciliation_status = SummaryReconciliationStatus.pending
    for extra in condition_ids[1:]:  # a compound header (e.g. flare + phosphorus) is separate actions
        clone = SummaryItem(
            summary_id=summary.id, position=_next_position(session, summary.id), header_text=item.header_text,
            condition_id=extra, location_text=item.location_text, primary_village_id=village.id,
            modifier=SummaryModifier.none, reported_count=item.reported_count, evidence_span=item.evidence_span,
            origin=item.origin, resolution=SummaryResolution.resolved,
        )
        session.add(clone)
        session.flush()
        out.new_item_ids.append(clone.id)
    if action.save_alias and _save_alias(session, item, village.id):
        out.alias_saved.append(item.id)


def _resolve_header(session: Session, summary: SummaryBulletin, task: SummaryReviewTask, item: SummaryItem,
                    action: ReviewAction, user_id: UUID | None, out: ResolveOutcome) -> None:
    if not action.condition_ids:
        raise ReviewError(f"Item {item.id}: condition_ids is required to resolve a header.")
    condition_ids = _require_conditions(session, action.condition_ids)
    header = item.header_text or item.location_text
    if action.save_mapping and _save_mapping(session, header, condition_ids, user_id):
        out.mapping_saved.append(header)
    session.flush()
    # Re-read the bulletin with the header known (this summary only, unless the mapping was saved).
    headers = header_dictionary_for_session(session)
    if normalize_token(header) not in {k for k, e in headers.by_name.items() if e.status == "approved"}:
        from .dtos import HeaderEntry

        headers = HeaderDictionarySnapshot(
            (*headers.entries, HeaderEntry(normalize_token(header), tuple(condition_ids), "approved", "review")),
            headers.action_cores, headers.header_fillers,
        )
    raw = session.get(RawMessage, summary.raw_message_id)
    anchor = summary.window_start.astimezone(BEIRUT).date() if summary.window_start else None
    result = parse_summary(raw.raw_text or "", build_gazetteer_snapshot(session), headers, LEXICON, anchor)
    existing = {(i.condition_id, i.primary_village_id) for i in session.scalars(select(SummaryItem).where(SummaryItem.summary_id == summary.id))}
    position = _next_position(session, summary.id)
    for parsed in result.items:
        key = (parsed.condition_id, parsed.primary_village.id)
        evidence = parsed.evidence_spans[0].text if parsed.evidence_spans else ""
        if key in existing or not evidence or evidence not in (raw.raw_text or ""):
            continue
        existing.add(key)
        row = SummaryItem(
            summary_id=summary.id, position=position, header_text=parsed.header_text, condition_id=parsed.condition_id,
            location_text=" | ".join(parsed.location_texts), primary_village_id=parsed.primary_village.id,
            secondary_village_id=parsed.secondary_village.id if parsed.secondary_village else None,
            modifier=SummaryModifier.between if parsed.secondary_village else SummaryModifier.none,
            reported_count=parsed.reported_count, evidence_span=evidence, origin=SummaryItemOrigin.parser,
            resolution=SummaryResolution.resolved,
        )
        session.add(row)
        session.flush()
        out.new_item_ids.append(row.id)
        position += 1


def resolve_review_task(
    session: Session, summary_id: int, request: ResolveRequest, user_id: UUID | None
) -> ResolveOutcome:
    summary, task = _open_task(session, summary_id)
    reasons = _reason_state(task)
    out = ResolveOutcome([], [], task.status.value, [], [])
    seen: set[int] = set()
    for action in request.actions:
        if action.item_id in seen:
            raise ReviewError(f"Item {action.item_id} appears twice in the request.")
        seen.add(action.item_id)
        item = session.get(SummaryItem, action.item_id)
        reason = reasons.get(action.item_id)
        if item is None or item.summary_id != summary.id or reason is None:
            raise ReviewError(f"Item {action.item_id} is not part of this summary's review task.", 404)
        if reason.get("handled"):
            raise ReviewError(f"Item {action.item_id} was already handled.", 409)
        rtype = reason.get("type")
        if action.action == "dismiss":
            if rtype == CASUALTY_REASON:
                item.reconciliation_status = SummaryReconciliationStatus.ambiguous
            _mark_handled(task, item.id, {"action": "dismiss", "by": str(user_id) if user_id else None})
        elif rtype == "unresolved_location" and action.action == "resolve":
            _resolve_location(session, summary, item, action, out)
            _mark_handled(task, item.id, {"action": "resolve", "village_id": action.village_id, "by": str(user_id) if user_id else None})
        elif rtype == "unknown_header" and action.action == "resolve":
            _resolve_header(session, summary, task, item, action, user_id, out)
            _mark_handled(task, item.id, {"action": "resolve", "condition_ids": action.condition_ids, "by": str(user_id) if user_id else None})
        elif rtype == CASUALTY_REASON and action.action == "create_incident":
            created = _create_incidents(session, summary, [item])
            if item.id not in created:
                raise ReviewError(f"Item {item.id}: the incident could not be created.", 409)
            item.created_incident_id = created[item.id].id
            item.reconciliation_status = SummaryReconciliationStatus.created
            _mark_handled(task, item.id, {"action": "create_incident", "by": str(user_id) if user_id else None})
        else:
            raise ReviewError(f"Action {action.action!r} is not valid for a {rtype!r} item.")
        out.handled_item_ids.append(item.id)
    _close_if_done(task, user_id, SummaryReviewStatus.resolved)
    session.flush()
    _queue(summary, session)
    out.task_status = task.status.value
    session.add_all([summary, task])
    session.flush()
    return out


def dismiss_review_task(session: Session, summary_id: int, user_id: UUID | None) -> None:
    summary, task = _open_task(session, summary_id)
    reasons = _reason_state(task)
    for item_id, reason in reasons.items():
        if reason.get("handled"):
            continue
        item = session.get(SummaryItem, item_id)
        if item is not None and reason.get("type") == CASUALTY_REASON:
            item.reconciliation_status = SummaryReconciliationStatus.ambiguous
        _mark_handled(task, item_id, {"action": "dismiss", "by": str(user_id) if user_id else None})
    _close_if_done(task, user_id, SummaryReviewStatus.dismissed)
    session.flush()
    _queue(summary, session)
    session.add_all([summary, task])
    session.flush()
