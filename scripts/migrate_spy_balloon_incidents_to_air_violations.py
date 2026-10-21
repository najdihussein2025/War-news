#!/usr/bin/env python
"""Move existing Spy Balloon (condition 34) incidents into Air Violations.

CNRS counts spy balloons as air violations (one breach per caza), so balloon
reports no longer belong in the incidents table. For every live incident with
condition 34 this creates the ``air_violations`` row (plus one location per
village) and soft-deletes the incident through the audited soft-delete boundary.
Nothing is hard-deleted.

Incidents that share a raw message become one air-violation row carrying all of
their villages. The script is idempotent: a raw message that already has an
air-violation row is skipped (incidents with no raw message are matched on
condition, date, time and text).

Dry-run is the default. Use ``--apply`` only after reviewing the output.

Usage:
  python scripts/migrate_spy_balloon_incidents_to_air_violations.py
  python scripts/migrate_spy_balloon_incidents_to_air_violations.py --apply
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import app.accounts.models  # noqa: F401,E402
import app.logs.models  # noqa: E402,F401
import app.sources.models  # noqa: E402,F401
from app.news.constants.air_violation_conditions import (  # noqa: E402
    AIR_VIOLATION_SPY_BALLOON_CONDITION_ID,
)
from app.news.models import (  # noqa: E402
    AirViolation,
    AirViolationLocation,
    Incident,
    RawMessage,
    Village,
)
from app.news.services.air_violations.war_month import war_month  # noqa: E402
from app.news.services.incidents.soft_delete import soft_delete_incident  # noqa: E402

# deleted_reason is a String(32) column.
DELETED_REASON = "SCRIPT_BALLOON_AIR_REROUTE"
assert len(DELETED_REASON) <= 32


@dataclass
class Summary:
    candidates: int = 0
    skipped_existing: int = 0
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def _group_key(incident: Incident) -> tuple[str, object]:
    if incident.raw_message_id is not None:
        return ("raw", incident.raw_message_id)
    return ("incident", incident.id)


def _already_migrated(db, incidents: list[Incident]) -> bool:
    first = incidents[0]
    if first.raw_message_id is not None:
        return db.scalar(
            select(AirViolation.id).where(
                AirViolation.raw_message_id == first.raw_message_id
            )
        ) is not None
    return db.scalar(
        select(AirViolation.id).where(
            AirViolation.condition_id == AIR_VIOLATION_SPY_BALLOON_CONDITION_ID,
            AirViolation.event_date == first.event_date,
            AirViolation.event_time == first.event_time,
            AirViolation.khabar == first.khabar,
        )
    ) is not None


def _source_id(db, incidents: list[Incident]) -> int | None:
    for incident in incidents:
        if incident.source_id is not None:
            return incident.source_id
    raw_message_id = incidents[0].raw_message_id
    message = db.get(RawMessage, raw_message_id) if raw_message_id is not None else None
    return message.source_id if message is not None else None


def build_air_violation(db, incidents: list[Incident]) -> AirViolation:
    """The air-violation row for one group of balloon incidents."""
    first = incidents[0]
    source_id = _source_id(db, incidents)
    if source_id is None:
        raise ValueError("no source_id on the incident or its raw message")

    villages: list[Village] = []
    seen: set[int] = set()
    for incident in incidents:
        if incident.village_id is None or incident.village_id in seen:
            continue
        seen.add(incident.village_id)
        village = db.get(Village, incident.village_id)
        if village is not None:
            villages.append(village)

    cazas = {(v.caza_en, v.caza_ar) for v in villages if v.caza_en or v.caza_ar}
    if len(cazas) > 1:
        caza_en, caza_ar = "Multiple regions", "مناطق متعددة"
    elif cazas:
        caza_en, caza_ar = next(iter(cazas))
    else:
        caza_en = caza_ar = None

    record = AirViolation(
        raw_message_id=first.raw_message_id,
        condition_id=AIR_VIOLATION_SPY_BALLOON_CONDITION_ID,
        source_id=source_id,
        village_id=villages[0].id if villages else None,
        caza_en=caza_en,
        caza_ar=caza_ar,
        event_month=first.event_month or first.event_date.strftime("%B"),
        war_month=war_month(first.event_date),
        event_date=first.event_date,
        event_time=first.event_time,
        khabar=first.khabar,
        note_1=first.note,
        source_link=first.source_link,
    )
    record.locations = [AirViolationLocation(village_id=v.id) for v in villages]
    return record


def run(db, *, apply: bool) -> Summary:
    summary = Summary()
    incidents = list(
        db.scalars(
            select(Incident)
            .where(
                Incident.condition_id == AIR_VIOLATION_SPY_BALLOON_CONDITION_ID,
                Incident.is_deleted.is_(False),
            )
            .order_by(Incident.event_date.asc(), Incident.event_time.asc())
        ).all()
    )
    groups: dict[tuple[str, object], list[Incident]] = defaultdict(list)
    for incident in incidents:
        groups[_group_key(incident)].append(incident)

    for group in groups.values():
        if _already_migrated(db, group):
            summary.skipped_existing += len(group)
            continue
        summary.candidates += len(group)
        if not apply:
            continue
        summary.processed += len(group)
        try:
            db.add(build_air_violation(db, group))
            for incident in group:
                soft_delete_incident(db, incident, reason=DELETED_REASON)
            db.commit()
            summary.succeeded += len(group)
        except Exception as exc:  # noqa: BLE001 - report and continue with the next group
            db.rollback()
            summary.failed += len(group)
            summary.errors.append(f"{[str(i.id) for i in group]}: {exc}")
    return summary


def print_summary(summary: Summary, *, apply: bool) -> None:
    mode = "apply" if apply else "dry run"
    print(f"=== spy balloon incidents -> air violations ({mode}) ===")
    print(f"candidate incidents: {summary.candidates}")
    print(f"skipped (air violation already exists): {summary.skipped_existing}")
    if apply:
        print(f"processed: {summary.processed}")
        print(f"succeeded: {summary.succeeded}")
        print(f"failed: {summary.failed}")
        for error in summary.errors:
            print(f"  failed: {error}")
    else:
        print("\nDry run only - no database writes. Re-run with --apply to migrate.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        print_summary(run(db, apply=args.apply), apply=args.apply)
    finally:
        db.close()


if __name__ == "__main__":
    main()
