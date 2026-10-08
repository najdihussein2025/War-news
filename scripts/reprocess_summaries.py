"""Backfill: reprocess old raw messages through the summary flow.

Three phases, each in message-time order:

1. intake    - detect/parse every summary bulletin and store it with its items.
2. old rows  - decide the incidents the old pipeline materialised *from the summary message itself*:
   ``unique_correct`` (restored if wrongly deleted, kept), ``duplicate`` (another incident already
   covers it; for two summary rows the earliest wins) and ``wrong`` (not in the parsed items).
   Rows deleted without a reason get one; nothing is hard-deleted.
3. reconcile - strict rules: link an existing incident (window or same local date), create an
   incident ONLY when the news never arrived and no incident sits at the village within +-1 day,
   and send everything else (failed/rejected news, wrong village, other action, invalid window,
   guard hits) to ONE review task per summary.

A dry run executes exactly the same code and rolls the whole transaction back, so its decisions
are the ones ``--apply`` will make. Non-summary incidents only ever receive the idempotent
confirmation note.

Usage (inside the backend container, DATABASE_URL pointing at the target database):
    python -m scripts.reprocess_summaries --since 2026-04-01 --until 2026-10-08 --crosscheck off
    python -m scripts.reprocess_summaries --since ... --until ... --crosscheck off --apply
    python -m scripts.reprocess_summaries --verify Docs/audits/<dir>/decisions.csv
"""
from __future__ import annotations

import argparse
import csv
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging_config import configure_logging
from app.news.models import Condition, Incident, IncidentOrigin, MessageStatus, RawMessage, UpdateAction, Village
from app.news.models.summary_bulletin import SummaryBulletin, SummaryItem, SummaryResolution, SummaryReviewTask, SummaryStatus
from app.news.services.incidents.incident_change_log import record_incident_change
from app.news.services.incidents.soft_delete import record_missing_deleted_reason, soft_delete_incident
from app.news.services.summaries.condition_families import ConditionFamilies, load_condition_families
from app.news.services.summaries.decision_reasons import append_note, note as decision_note
from app.news.services.summaries.gap_classification import GapClassifier
from app.news.services.summaries.intake_service import intake_summary
from app.news.services.summaries.reconcile_service import StrictContext, reconcile_summary
from app.news.services.summaries.routing import run_coroutine_sync

logger = logging.getLogger(__name__)

OldIncidentClass = Literal["unique_correct", "duplicate_of_live", "duplicate_of_summary_row", "wrong"]
FALLBACK_OUTCOMES = frozenset({"not_summary", "not_a_summary", "failed", "already_processed"})
LEGACY_SUFFIX = "\n(حُذف سابقاً بدون سبب مسجل)"
REASON_BY_CLASS = {
    "duplicate_of_live": "REJECTED_DUPLICATE",
    "duplicate_of_summary_row": "REJECTED_DUPLICATE_SUMMARY_ROW",
    "wrong": "REJECTED_WRONG_ROW",
}


@dataclass
class OldIncidentRow:
    incident_id: str
    village_id: int | None
    condition_id: int | None
    classification: OldIncidentClass
    detail: str
    was_deleted_without_reason: bool = False
    kept_incident_id: str | None = None
    action: str = ""


@dataclass
class MessageResult:
    raw_message_id: int
    message_datetime: datetime | None
    channel: str | None
    summary_id: int | None
    summary_outcome: str
    item_count: int
    old_incidents: list[OldIncidentRow] = field(default_factory=list)
    applied: bool = False
    error: str | None = None


@dataclass
class RunState:
    families: ConditionFamilies
    summary_ids: set[int] = field(default_factory=set)
    strict: StrictContext | None = None
    results: dict[int, MessageResult] = field(default_factory=dict)
    changes: Counter = field(default_factory=Counter)
    order: dict[int, tuple[datetime, int]] = field(default_factory=dict)


def select_candidate_messages(session: Session, since: date, until: date, limit: int | None) -> list[int]:
    """All possible bulletins in order, including earlier summary rows needing repair."""
    query = (
        select(RawMessage.id)
        .where(
            RawMessage.raw_text.is_not(None),
            RawMessage.message_datetime >= datetime.combine(since, datetime.min.time(), tzinfo=timezone.utc),
            RawMessage.message_datetime < datetime.combine(until, datetime.min.time(), tzinfo=timezone.utc) + timedelta(days=1),
        )
        .order_by(RawMessage.message_datetime.asc(), RawMessage.id.asc())
    )
    if limit is not None:
        query = query.limit(limit)
    return list(session.scalars(query))


def _old_path_incidents(session: Session, raw_message_id: int) -> list[Incident]:
    return list(
        session.scalars(
            select(Incident).where(
                Incident.raw_message_id == raw_message_id,
                Incident.origin == IncidentOrigin.live,
                # Include historical deletes with no reason so they can be classified
                # and either retained-with-a-decision or restored in place.
                (Incident.is_deleted.is_(False) | Incident.deleted_reason.is_(None)),
            ).order_by(Incident.created_at, Incident.id)
        )
    )


def _raw_order(session: Session, raw_message_id: int, cache: dict[int, tuple[datetime, int]]) -> tuple[datetime, int]:
    if raw_message_id not in cache:
        moment = session.scalar(select(RawMessage.message_datetime).where(RawMessage.id == raw_message_id))
        cache[raw_message_id] = (moment or datetime.min.replace(tzinfo=timezone.utc), raw_message_id)
    return cache[raw_message_id]


def _other_covering_incident(
    session: Session, *, incident: Incident, raw_message: RawMessage, summary_ids: set[int],
    families: ConditionFamilies, order: dict[int, tuple[datetime, int]], tolerance_days: int = 1,
) -> tuple[Incident | None, bool]:
    """(covering incident, covering incident is another summary row). For two summary rows the earliest wins."""
    if incident.village_id is None or incident.condition_id is None:
        return None, False
    mine = _raw_order(session, raw_message.id, order)
    rows = session.scalars(select(Incident).where(
        Incident.village_id == incident.village_id,
        Incident.condition_id.in_(sorted(families.equivalents(incident.condition_id))),
        Incident.is_deleted.is_(False),
        Incident.raw_message_id.is_not(None),
        Incident.raw_message_id != raw_message.id,
        Incident.id != incident.id,
        Incident.event_date >= incident.event_date - timedelta(days=tolerance_days),
        Incident.event_date <= incident.event_date + timedelta(days=tolerance_days),
    ).order_by(Incident.created_at, Incident.id)).all()
    for other in rows:
        if other.raw_message_id not in summary_ids:
            return other, False
    for other in rows:
        if _raw_order(session, other.raw_message_id, order) < mine:
            return other, True
    return None, False


def classify_old_incidents(
    session: Session, raw_message: RawMessage, parsed_items: list[SummaryItem], families: ConditionFamilies,
    *, summary_ids: set[int] | None = None, order: dict[int, tuple[datetime, int]] | None = None,
) -> list[OldIncidentRow]:
    summary_ids = summary_ids if summary_ids is not None else set()
    order = order if order is not None else {}
    parsed_pairs = {
        (item.primary_village_id, item.condition_id) for item in parsed_items if item.primary_village_id
    } | {
        (item.secondary_village_id, item.condition_id) for item in parsed_items if item.secondary_village_id
    }
    rows: list[OldIncidentRow] = []
    for incident in _old_path_incidents(session, raw_message.id):
        legacy = bool(incident.is_deleted and incident.deleted_reason is None)
        other, is_summary_row = _other_covering_incident(
            session, incident=incident, raw_message=raw_message, summary_ids=summary_ids, families=families, order=order,
        )
        if other is not None:
            kind: OldIncidentClass = "duplicate_of_summary_row" if is_summary_row else "duplicate_of_live"
            rows.append(OldIncidentRow(str(incident.id), incident.village_id, incident.condition_id, kind,
                f"incident {other.id} already covers this event", legacy, str(other.id)))
        elif (incident.village_id, incident.condition_id) in parsed_pairs:
            rows.append(OldIncidentRow(str(incident.id), incident.village_id, incident.condition_id,
                "unique_correct", "matches a parsed summary item; kept active so reconciliation links it", legacy))
        else:
            rows.append(OldIncidentRow(str(incident.id), incident.village_id, incident.condition_id,
                "wrong", "village/condition is not among the parsed items", legacy))
    return rows


def _canonical(session: Session, summary: SummaryBulletin) -> SummaryBulletin:
    return session.get(SummaryBulletin, summary.canonical_summary_id) if summary.canonical_summary_id else summary


def _parsed_items(session: Session, summary: SummaryBulletin) -> list[SummaryItem]:
    owner = _canonical(session, summary)
    return list(session.scalars(select(SummaryItem).where(
        SummaryItem.summary_id == owner.id, SummaryItem.resolution == SummaryResolution.resolved,
    )))


def phase_intake(session: Session, raw_message_id: int, *, crosscheck: bool, state: RunState) -> MessageResult | None:
    """Store the bulletin and its items. Returns None when the message is not a (usable) summary."""
    nested = session.begin_nested()
    try:
        raw_message = session.get(RawMessage, raw_message_id)
        assert raw_message is not None
        existing = session.scalar(select(SummaryBulletin).where(SummaryBulletin.raw_message_id == raw_message.id))
        if existing is None:
            intake = run_coroutine_sync(intake_summary(session, raw_message, crosscheck_enabled=crosscheck))
            if intake.outcome in FALLBACK_OUTCOMES:
                nested.rollback()
                return None
            summary_id, outcome = intake.summary_id, intake.outcome
            state.changes["summary_created"] += 1
        else:
            if existing.status == SummaryStatus.failed:
                nested.rollback()
                return None
            summary_id, outcome = existing.id, "existing_summary"
        session.flush()
        count = session.scalar(select(func.count()).select_from(SummaryItem).where(SummaryItem.summary_id == summary_id)) or 0
        nested.commit()
        return MessageResult(raw_message_id, raw_message.message_datetime, raw_message.source_name, summary_id, outcome, count)
    except Exception as exc:  # noqa: BLE001 - recorded per-message, loop continues
        nested.rollback()
        logger.exception("reprocess_summaries intake failed raw_message_id=%s", raw_message_id)
        return MessageResult(raw_message_id, None, None, None, "error", 0, [], False, str(exc)[:500])


def _names(session: Session, incident: Incident) -> tuple[str, str]:
    village = session.scalar(select(Village.ref_name_ar).where(Village.id == incident.village_id)) or str(incident.village_id)
    action = session.scalar(select(Condition.action_ar).where(Condition.id == incident.condition_id)) or str(incident.condition_id)
    return village, action


def phase_old_rows(session: Session, result: MessageResult, *, state: RunState) -> None:
    raw_message = session.get(RawMessage, result.raw_message_id)
    summary = session.get(SummaryBulletin, result.summary_id)
    assert raw_message is not None and summary is not None
    result.old_incidents = classify_old_incidents(
        session, raw_message, _parsed_items(session, summary), state.families, summary_ids=state.summary_ids, order=state.order,
    )
    owner = _canonical(session, summary)
    summary_date = (owner.window_end or owner.created_at).astimezone(timezone.utc).date().isoformat()
    items = list(session.scalars(select(SummaryItem).where(SummaryItem.summary_id == summary.id)))
    for row in result.old_incidents:
        incident = session.get(Incident, row.incident_id)
        if incident is None:
            continue
        suffix = LEGACY_SUFFIX if row.was_deleted_without_reason else ""
        if row.classification == "unique_correct":
            if incident.decision_reason == "ACCEPTED_CONFIRMED_BY_SUMMARY" and not incident.is_deleted:
                row.action = "kept"
                continue
            if incident.is_deleted:
                incident.is_deleted = False
                incident.deleted_reason = None
                record_incident_change(
                    session, incident_id=incident.id, action=UpdateAction.status_change,
                    old_values={"is_deleted": True, "deleted_reason": None},
                    new_values={"is_deleted": False, "decision_reason": "ACCEPTED_CONFIRMED_BY_SUMMARY"},
                    performed_by=None,
                )
                state.changes["restored"] += 1
                row.action = "restored"
            else:
                row.action = "kept"
            incident.decision_reason = "ACCEPTED_CONFIRMED_BY_SUMMARY"
            incident.decision_source_summary_id = summary.id
            incident.decided_at = datetime.now(timezone.utc)
            incident.note = append_note(incident.note, decision_note(
                "ACCEPTED_CONFIRMED_BY_SUMMARY", summary_channel=summary.channel, summary_date=summary_date,
            ) + suffix)
            state.changes["decision_stamped"] += 1
            for item in items:
                if item.matched_incident_id is None and incident.village_id in {item.primary_village_id, item.secondary_village_id} and incident.condition_id == item.condition_id:
                    item.matched_incident_id = incident.id
                    break
            continue
        reason = REASON_BY_CLASS[row.classification]
        if incident.decision_reason == reason and incident.deleted_reason is not None:
            row.action = "soft_removed"
            continue
        village, action = _names(session, incident)
        kept = session.get(Incident, row.kept_incident_id) if row.kept_incident_id else None
        kept_channel = (session.scalar(select(RawMessage.source_name).where(RawMessage.id == kept.raw_message_id)) if kept is not None and kept.raw_message_id else "") or ""
        incident.decision_reason = reason
        incident.decision_source_summary_id = summary.id
        incident.decision_ref_incident_id = kept.id if kept is not None else None
        incident.decided_at = datetime.now(timezone.utc)
        incident.note = append_note(incident.note, decision_note(
            reason, village=village, action=action, summary_channel=summary.channel, summary_date=summary_date,
            dup_short_id=str(kept.id)[:8] if kept is not None else "", dup_channel=kept_channel,
            dup_time=kept.event_time.strftime("%H:%M") if kept is not None and kept.event_time else "",
            kept_short_id=str(kept.id)[:8] if kept is not None else "", hint="",
        ) + suffix)
        state.changes["decision_stamped"] += 1
        if incident.is_deleted:
            if record_missing_deleted_reason(session, incident, reason=reason):
                state.changes["deleted_reason_filled"] += 1
        else:
            soft_delete_incident(session, incident, reason=reason, canonical_incident_id=kept.id if kept is not None else None)
            state.changes["soft_deleted"] += 1
        row.action = "soft_removed"
    session.flush()


def phase_reconcile(session: Session, result: MessageResult, *, state: RunState) -> None:
    raw_message = session.get(RawMessage, result.raw_message_id)
    assert raw_message is not None and state.strict is not None
    nested = session.begin_nested()
    try:
        reconcile = run_coroutine_sync(reconcile_summary(session, result.summary_id, dry_run=False, strict=state.strict))
        if raw_message.status != MessageStatus.summary_handled or raw_message.error_message is not None:
            raw_message.status = MessageStatus.summary_handled
            raw_message.error_message = None
            session.add(raw_message)
            state.changes["raw_message_handled"] += 1
        session.flush()
        result.summary_outcome = reconcile.outcome
        result.applied = True
        nested.commit()
    except Exception as exc:  # noqa: BLE001
        nested.rollback()
        logger.exception("reprocess_summaries reconcile failed raw_message_id=%s", result.raw_message_id)
        result.summary_outcome, result.error = "error", str(exc)[:500]


def run_backfill(session: Session, message_ids: list[int], *, apply: bool, crosscheck: bool, batch: int, families: ConditionFamilies | None = None) -> RunState:
    state = RunState(families=families or load_condition_families(session))
    results: list[MessageResult] = []
    for index, message_id in enumerate(message_ids, start=1):
        result = phase_intake(session, message_id, crosscheck=crosscheck, state=state)
        if result is not None:
            results.append(result)
        if apply and index % batch == 0:
            session.commit()
    if apply:
        session.commit()
    ok = [r for r in results if r.summary_outcome != "error"]
    state.summary_ids = set(session.scalars(select(SummaryBulletin.raw_message_id).where(SummaryBulletin.status != SummaryStatus.failed))) | {r.raw_message_id for r in ok}
    state.strict = StrictContext(summary_message_ids=state.summary_ids)
    state.strict.classifier = GapClassifier(
        session, summary_message_ids=state.summary_ids, tolerance_minutes=settings.summary_match_tolerance_minutes)
    for position, result in enumerate(ok, start=1):
        phase_old_rows(session, result, state=state)
        if apply and position % batch == 0:
            session.commit()
    if apply:
        session.commit()
    for position, result in enumerate(ok, start=1):
        phase_reconcile(session, result, state=state)
        if apply and position % batch == 0:
            session.commit()
    if apply:
        session.commit()
    for key, value in state.strict.changes.items():
        state.changes[key] += value
    state.results = {r.raw_message_id: r for r in results}
    return state


def write_outputs(state: RunState, *, apply: bool, since: date, until: date, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    results = list(state.results.values())
    strict = state.strict
    assert strict is not None
    errors = [r for r in results if r.summary_outcome == "error"]
    old_counts = Counter(row.classification for r in results for row in r.old_incidents)
    outcome_counts = Counter((e["outcome"], e["reason"]) for e in strict.events)
    today = date.today().isoformat()
    lines = [
        f"# Summary backfill {'apply' if apply else 'dry run'} — {today}", "",
        f"Range: {since.isoformat()} to {until.isoformat()}. Messages matched as summaries: {len(results)}.",
        f"Old-path rows: {sum(old_counts.values())} — " + ", ".join(f"{k}={v}" for k, v in sorted(old_counts.items())) + ".",
        f"Item decisions: " + ", ".join(f"{o}/{r or '-'}={n}" for (o, r), n in sorted(outcome_counts.items())) + ".",
        f"Writes: " + (", ".join(f"{k}={v}" for k, v in sorted(state.changes.items())) or "none") + f" (total {sum(state.changes.values())}).",
        f"Errors: {len(errors)}.", "",
        "| raw_message_id | summary_id | channel | outcome | items | unique_correct | duplicate | wrong |", "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        by = Counter(row.classification for row in r.old_incidents)
        lines.append(f"| {r.raw_message_id} | {r.summary_id} | {r.channel or ''} | {r.summary_outcome} | {r.item_count} | {by['unique_correct']} | {by['duplicate_of_live'] + by['duplicate_of_summary_row']} | {by['wrong']} |")
    if errors:
        lines += ["", "## Errors", ""] + [f"- raw_message_id={r.raw_message_id}: {r.error}" for r in errors]
    paths = {"report": out_dir / ("apply_report.md" if apply else "report.md"), "decisions": out_dir / "decisions.csv"}
    paths["report"].write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    with paths["decisions"].open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["scope", "summary_raw_message_id", "key", "village_id", "condition_id", "outcome", "reason", "ref"])
        for r in results:
            for row in r.old_incidents:
                reason = "ACCEPTED_CONFIRMED_BY_SUMMARY" if row.classification == "unique_correct" else REASON_BY_CLASS[row.classification]
                writer.writerow(["old_row", r.raw_message_id, row.incident_id, row.village_id, row.condition_id, row.action or ("kept" if row.classification == "unique_correct" else "soft_removed"), reason, row.kept_incident_id or ""])
        for e in strict.events:
            writer.writerow(["item", e["summary_raw_message_id"], e["item_position"], e["village_id"], e["condition_id"], e["outcome"], e["reason"], e["raw_message_ids"] if e["reason"] in {"NEWS_FAILED", "NEWS_REJECTED", "NEWS_WRONG_VILLAGE"} else ""])
    review_dir = out_dir / "review_lists"
    review_dir.mkdir(exist_ok=True)
    fields = ["summary_raw_message_id", "item_position", "village_id", "condition_id", "reason", "raw_message_ids", "incident_ids"]
    by_reason: dict[str, list[dict]] = {}
    for e in strict.events:
        if e["outcome"] == "review":
            by_reason.setdefault(e["reason"].lower(), []).append(e)
    for reason, events in by_reason.items():
        with (review_dir / f"{reason}.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(events)
    paths["failed"] = out_dir / "failed_to_reprocess.csv"
    with paths["failed"].open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["raw_message_id", "summary_raw_message_id"])
        seen: set[int] = set()
        for summary_raw, ids in sorted(strict.failed_raw_ids.items()):
            for raw_id in sorted(ids):
                if raw_id not in seen:
                    seen.add(raw_id)
                    writer.writerow([raw_id, summary_raw])
    return paths


def verify_against(session: Session, decisions_csv: Path) -> int:
    """Compare what is in the database with a dry-run decisions.csv. Returns the number of differences."""
    differences = 0
    with decisions_csv.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        if row["scope"] == "old_row":
            incident = session.get(Incident, row["key"])
            expected_removed = row["outcome"] == "soft_removed"
            ok = incident is not None and incident.decision_reason == row["reason"] and incident.is_deleted == expected_removed and (not expected_removed or incident.deleted_reason is not None)
            if not ok:
                differences += 1
                print(f"DIFF old_row {row['key']}: expected {row['outcome']}/{row['reason']}")
        else:
            summary = session.scalar(select(SummaryBulletin).where(SummaryBulletin.raw_message_id == int(row["summary_raw_message_id"])))
            item = session.scalar(select(SummaryItem).where(SummaryItem.summary_id == summary.id, SummaryItem.position == int(row["key"]))) if summary else None
            if item is None:
                differences += 1
                print(f"DIFF item missing {row['summary_raw_message_id']}#{row['key']}")
                continue
            if row["outcome"] == "matched":
                ok = item.reconciliation_status.value == "matched"
            elif row["outcome"] == "created":
                created = session.get(Incident, item.created_incident_id) if item.created_incident_id else None
                ok = item.reconciliation_status.value == "created" and created is not None and created.decision_reason == "ACCEPTED_MISSED_NEVER_ARRIVED" and not created.is_deleted
            else:
                task = session.scalar(select(SummaryReviewTask).where(SummaryReviewTask.summary_id == summary.id))
                wanted = row["reason"].lower() if row["reason"] != "NEARBY_INCIDENT_GUARD" else "nearby_incident_guard"
                ok = task is not None and any(r.get("type") == wanted and item.id in (r.get("item_ids") or []) for r in task.reasons or []) and item.created_incident_id is None
            if not ok:
                differences += 1
                print(f"DIFF item {row['summary_raw_message_id']}#{row['key']}: expected {row['outcome']}/{row['reason']}")
    print(f"verify rows={len(rows)} differences={differences}")
    return differences


def main() -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--since", type=date.fromisoformat)
    parser.add_argument("--until", type=date.fromisoformat)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--batch", type=int, default=50, help="Commit boundary for --apply (default: 50).")
    parser.add_argument("--crosscheck", choices=("off", "on"), default="off", help="Use add-only LLM cross-check for this backfill only (default: off).")
    parser.add_argument("--apply", action="store_true", help="Write real changes (default is a dry run that rolls back).")
    parser.add_argument("--out", type=Path, default=None, help="Output directory (default Docs/audits/summary_cleanup_dryrun_<today>).")
    parser.add_argument("--verify", type=Path, help="Compare the database against a decisions.csv and exit.")
    args = parser.parse_args()

    if args.verify:
        with SessionLocal() as session:
            return 0 if verify_against(session, args.verify) == 0 else 1
    if not args.since or not args.until:
        parser.error("--since and --until are required")

    with SessionLocal() as session:
        message_ids = select_candidate_messages(session, args.since, args.until, args.limit)
        state = run_backfill(session, message_ids, apply=args.apply, crosscheck=args.crosscheck == "on", batch=args.batch)
        if not args.apply:
            session.rollback()
    out_dir = args.out or Path("Docs/audits") / f"summary_cleanup_dryrun_{date.today().isoformat()}"
    paths = write_outputs(state, apply=args.apply, since=args.since, until=args.until, out_dir=out_dir)
    failed = sum(1 for r in state.results.values() if r.summary_outcome == "error")
    total_changes = sum(state.changes.values())
    print(f"Summary backfill mode={'apply' if args.apply else 'dry_run'} processed={len(state.results)} failed={failed} changes={total_changes}")
    print("changes_detail=" + ",".join(f"{k}={v}" for k, v in sorted(state.changes.items())))
    for name, path in paths.items():
        print(f"{name}: {path}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
