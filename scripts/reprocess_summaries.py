"""Backfill: reprocess old raw messages through the summary flow.

Finds raw messages in a date range that ``detect_summary``/the parser's false-positive
guard accept as real summary bulletins, runs intake + reconciliation on them, and
classifies the *old-path* incidents already materialized from that same raw message:

* ``unique_correct``  - matches one parsed item and no other (different-message) incident
  exists for that village/condition/window. Left active: reconciliation links it as the
  item's matched incident instead of creating a new one.
* ``duplicate_of_live`` - another live incident from a *different* message already covers
  the same village + condition family + window. Soft-removed.
* ``wrong`` - its village/condition is not among the parsed items (an invented village or a
  wrong-district match). Soft-removed.

Default is a dry run: nothing is written except the report and CSV. ``--apply`` runs the
real intake + reconciliation and the soft-removals, one transaction per message, in
message-time order. Non-summary incidents (any raw message that is not itself a detected
summary) are never touched.

Usage (dev stack):
    docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml \
        exec backend python -m scripts.reprocess_summaries --since 2026-09-01 --until 2026-10-01
    ... --apply --limit 50
"""
from __future__ import annotations

import argparse
import csv
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.logging_config import configure_logging
from app.news.models import Incident, IncidentOrigin, MessageStatus, RawMessage
from app.news.models.summary_bulletin import SummaryBulletin, SummaryItem, SummaryResolution
from app.news.repositories.incident_repository import IncidentRepository
from app.news.services.summaries.condition_families import ConditionFamilies, load_condition_families
from app.news.services.summaries.intake_service import intake_summary
from app.news.services.summaries.reconcile_service import reconcile_summary
from app.news.services.summaries.routing import run_coroutine_sync

logger = logging.getLogger(__name__)

OldIncidentClass = Literal["unique_correct", "duplicate_of_live", "wrong"]


@dataclass
class OldIncidentRow:
    incident_id: str
    village_id: int | None
    condition_id: int | None
    classification: OldIncidentClass
    detail: str


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


def select_candidate_messages(session: Session, since: date, until: date, limit: int | None) -> list[int]:
    """Raw messages in range with no summary row yet, oldest first."""
    already_summary = select(SummaryBulletin.raw_message_id)
    query = (
        select(RawMessage.id)
        .where(
            RawMessage.raw_text.is_not(None),
            RawMessage.message_datetime >= datetime.combine(since, datetime.min.time(), tzinfo=timezone.utc),
            RawMessage.message_datetime < datetime.combine(until, datetime.min.time(), tzinfo=timezone.utc) + timedelta(days=1),
            RawMessage.id.not_in(already_summary),
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
                Incident.is_deleted.is_(False),
            )
        )
    )


def _other_live_match_exists(
    session: Session, *, village_id: int | None, condition_id: int | None, event_date: date,
    exclude_raw_message_id: int, families: ConditionFamilies, tolerance_days: int = 1,
) -> bool:
    if village_id is None or condition_id is None:
        return False
    rows = session.scalars(
        select(Incident).where(
            Incident.village_id == village_id,
            Incident.condition_id.in_(sorted(families.equivalents(condition_id))),
            Incident.is_deleted.is_(False),
            Incident.raw_message_id.is_not(None),
            Incident.raw_message_id != exclude_raw_message_id,
            Incident.event_date >= event_date - timedelta(days=tolerance_days),
            Incident.event_date <= event_date + timedelta(days=tolerance_days),
        )
    ).all()
    return bool(rows)


def classify_old_incidents(
    session: Session, raw_message: RawMessage, parsed_items: list[SummaryItem], families: ConditionFamilies,
) -> list[OldIncidentRow]:
    parsed_pairs = {
        (item.primary_village_id, item.condition_id) for item in parsed_items if item.primary_village_id
    } | {
        (item.secondary_village_id, item.condition_id) for item in parsed_items if item.secondary_village_id
    }
    rows: list[OldIncidentRow] = []
    for incident in _old_path_incidents(session, raw_message.id):
        if _other_live_match_exists(
            session, village_id=incident.village_id, condition_id=incident.condition_id,
            event_date=incident.event_date, exclude_raw_message_id=raw_message.id, families=families,
        ):
            rows.append(OldIncidentRow(str(incident.id), incident.village_id, incident.condition_id,
                "duplicate_of_live", "another live incident from a different message already covers this event"))
        elif (incident.village_id, incident.condition_id) in parsed_pairs:
            rows.append(OldIncidentRow(str(incident.id), incident.village_id, incident.condition_id,
                "unique_correct", "matches a parsed summary item; kept active so reconciliation links it"))
        else:
            rows.append(OldIncidentRow(str(incident.id), incident.village_id, incident.condition_id,
                "wrong", "village/condition is not among the parsed items"))
    return rows


FALLBACK_OUTCOMES = frozenset({"not_summary", "not_a_summary", "failed", "already_processed"})


def process_message(session: Session, raw_message_id: int, *, apply: bool, families: ConditionFamilies) -> MessageResult | None:
    """Returns None when the message is not a (usable) summary; otherwise the full result.

    Runs inside a SAVEPOINT so a dry run (or an error) never leaves partial writes.
    """
    nested = session.begin_nested()
    try:
        raw_message = session.get(RawMessage, raw_message_id)
        assert raw_message is not None
        intake = run_coroutine_sync(intake_summary(session, raw_message))
        if intake.outcome in FALLBACK_OUTCOMES:
            nested.rollback()
            return None
        session.flush()
        parsed_items = list(
            session.scalars(
                select(SummaryItem).where(
                    SummaryItem.summary_id == intake.summary_id, SummaryItem.resolution == SummaryResolution.resolved,
                )
            )
        )
        old_rows = classify_old_incidents(session, raw_message, parsed_items, families)
        result = MessageResult(
            raw_message_id, raw_message.message_datetime, raw_message.source_name,
            intake.summary_id, intake.outcome, len(parsed_items), old_rows,
        )
        if apply:
            repo = IncidentRepository(session)
            for row in old_rows:
                if row.classification == "unique_correct":
                    continue
                incident = session.get(Incident, row.incident_id)
                if incident is not None:
                    repo.soft_delete_superseded_by_summary(
                        incident, canonical_incident_id=None,
                        note=f"Superseded by summary {intake.summary_id} (backfill {date.today().isoformat()}): {row.detail}.",
                    )
            session.flush()
            reconcile_result = run_coroutine_sync(reconcile_summary(session, intake.summary_id, dry_run=False))
            raw_message.status = MessageStatus.summary_handled
            raw_message.error_message = None
            session.add(raw_message)
            session.flush()
            result.summary_outcome = reconcile_result.outcome
            result.applied = True
            nested.commit()
        else:
            # Dry run: still see the proposed reconciliation outcome, but write nothing.
            run_coroutine_sync(reconcile_summary(session, intake.summary_id, dry_run=True))
            nested.rollback()
        return result
    except Exception as exc:  # noqa: BLE001 - recorded per-message, loop continues
        nested.rollback()
        logger.exception("reprocess_summaries failed raw_message_id=%s", raw_message_id)
        return MessageResult(raw_message_id, None, None, None, "error", 0, [], False, str(exc)[:500])


def write_report(results: list[MessageResult], *, apply: bool, since: date, until: date) -> tuple[Path, Path]:
    today = date.today().isoformat()
    docs_dir = Path("Docs/audits")
    docs_dir.mkdir(parents=True, exist_ok=True)
    md_path = docs_dir / f"summary_backfill_{'apply' if apply else 'dryrun'}_{today}.md"
    csv_path = docs_dir / f"summary_backfill_{'apply' if apply else 'dryrun'}_{today}.csv"

    counts = {"unique_correct": 0, "duplicate_of_live": 0, "wrong": 0}
    errors = [r for r in results if r.summary_outcome == "error"]
    for result in results:
        for row in result.old_incidents:
            counts[row.classification] += 1

    lines = [
        f"# Summary backfill {'apply' if apply else 'dry run'} — {today}",
        "",
        f"Range: {since.isoformat()} to {until.isoformat()}. Messages matched as summaries: {len(results)}.",
        f"Old-path incidents: {sum(counts.values())} total — "
        f"unique_correct={counts['unique_correct']}, duplicate_of_live={counts['duplicate_of_live']}, wrong={counts['wrong']}.",
        f"Errors: {len(errors)}.",
        "",
        "| raw_message_id | summary_id | channel | outcome | items | unique_correct | duplicate_of_live | wrong |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for result in results:
        by_class = {"unique_correct": 0, "duplicate_of_live": 0, "wrong": 0}
        for row in result.old_incidents:
            by_class[row.classification] += 1
        lines.append(
            f"| {result.raw_message_id} | {result.summary_id} | {result.channel or ''} | {result.summary_outcome} | "
            f"{result.item_count} | {by_class['unique_correct']} | {by_class['duplicate_of_live']} | {by_class['wrong']} |"
        )
    if errors:
        lines += ["", "## Errors", ""]
        lines += [f"- raw_message_id={r.raw_message_id}: {r.error}" for r in errors]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["raw_message_id", "summary_id", "incident_id", "village_id", "condition_id", "classification", "detail", "proposed_action"])
        for result in results:
            for row in result.old_incidents:
                action = "kept_active_linked_by_reconciliation" if row.classification == "unique_correct" else (
                    "soft_removed" if apply else "would_soft_remove"
                )
                writer.writerow([result.raw_message_id, result.summary_id, row.incident_id, row.village_id, row.condition_id, row.classification, row.detail, action])
    return md_path, csv_path


def main() -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", required=True, type=date.fromisoformat)
    parser.add_argument("--until", required=True, type=date.fromisoformat)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--apply", action="store_true", help="Write real changes (default is a dry run).")
    args = parser.parse_args()

    processed = succeeded = failed = 0
    results: list[MessageResult] = []
    with SessionLocal() as session:
        families = load_condition_families(session)
        message_ids = select_candidate_messages(session, args.since, args.until, args.limit)
        for raw_message_id in message_ids:
            result = process_message(session, raw_message_id, apply=args.apply, families=families)
            if args.apply:
                session.commit()
            else:
                session.rollback()
            if result is None:
                continue
            processed += 1
            if result.summary_outcome == "error":
                failed += 1
            else:
                succeeded += 1
            results.append(result)

    md_path, csv_path = write_report(results, apply=args.apply, since=args.since, until=args.until)
    line = f"Summary backfill mode={'apply' if args.apply else 'dry_run'} processed={processed} succeeded={succeeded} failed={failed}"
    logger.info("%s report=%s csv=%s", line, md_path, csv_path)
    print(line)
    print(f"Report: {md_path}")
    print(f"CSV: {csv_path}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
