"""Read-only before/after snapshot of the summary cleanup, and the checks that compare two snapshots.

    python -m scripts.summary_cleanup_snapshot --out before.json
    python -m scripts.summary_cleanup_snapshot --compare before.json after.json

The snapshot opens its own READ ONLY transaction. "Non-summary incidents" are the live incidents whose raw
message is NOT a real summary bulletin (computed in memory with the same acceptance guard as the audit), so
the set is identical before and after the backfill creates summary rows.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.news.models import RawMessage
from app.news.services.summaries.acceptance import accepted_parse
from app.news.services.summaries.gazetteer import build_gazetteer_snapshot
from app.news.services.summaries.header_store import header_dictionary_for_session

CORE_COLUMNS = (
    "village_id", "condition_id", "event_date", "event_time", "khabar", "deaths", "injuries", "total_deaths",
    "total_injuries", "is_deleted", "deleted_reason", "decision_reason", "verification_status", "origin", "raw_message_id",
)
CONFIRMATION = "مؤكد في ملخص"


def _digest(*parts) -> str:
    return hashlib.sha256("|".join("" if p is None else str(p) for p in parts).encode("utf-8")).hexdigest()


def take_snapshot(since: date) -> dict:
    engine = create_engine(settings.database_url, connect_args={"options": "-c default_transaction_read_only=on"})
    Session = sessionmaker(bind=engine, autoflush=False)
    with Session() as session:
        if str(session.execute(text("SHOW transaction_read_only")).scalar_one()).lower() not in {"on", "true"}:
            raise RuntimeError("refusing to snapshot: transaction is not read-only")
        gazetteer, headers = build_gazetteer_snapshot(session), header_dictionary_for_session(session)
        summary_ids: set[int] = set()
        from sqlalchemy import select
        for raw in session.scalars(select(RawMessage).where(RawMessage.raw_text.is_not(None), RawMessage.message_datetime >= datetime.combine(since, datetime.min.time(), tzinfo=timezone.utc))):
            if accepted_parse(raw, gazetteer, headers):
                summary_ids.add(raw.id)
        rows = session.execute(text(f"select id::text, raw_message_id, note, updated_at, {', '.join(CORE_COLUMNS)} from incidents")).mappings().all()
        non_summary = {}
        for row in rows:
            if row["origin"] == "live" and row["raw_message_id"] not in summary_ids:
                core = _digest(*(row[c] for c in CORE_COLUMNS))
                non_summary[row["id"]] = {"core": core, "note": row["note"] or "", "updated_at": row["updated_at"].isoformat()}
        visible = [r for r in rows if not r["is_deleted"]]
        deleted = Counter((r["deleted_reason"] or "(none)") for r in rows if r["is_deleted"])
        decisions = Counter((r["decision_reason"] or "(none)") for r in rows if r["decision_reason"])
        created = [r for r in rows if r["decision_reason"] == "ACCEPTED_MISSED_NEVER_ARRIVED" and not r["is_deleted"]]
        duplicates = 0
        for r in created:
            duplicates += session.execute(text(
                "select count(*) from incidents o, incidents i where i.id::text=:id and o.id<>i.id and not o.is_deleted "
                "and o.village_id=i.village_id and o.event_date between i.event_date - 1 and i.event_date + 1"), {"id": r["id"]}).scalar_one()
        counts = {
            "visible_incidents": len(visible),
            "needs_verification_visible": sum(1 for r in visible if r["verification_status"] == "needs_verification"),
            "incidents_total": len(rows),
            "by_origin_visible": dict(Counter(str(r["origin"]) for r in visible)),
            "deleted_by_reason": dict(deleted),
            "decisions_by_reason": dict(decisions),
            "created_never_arrived": len(created),
            "created_duplicate_neighbours": int(duplicates),
            "summary_bulletins": session.execute(text("select count(*) from summary_bulletins")).scalar_one(),
            "review_tasks": session.execute(text("select count(*) from summary_review_tasks")).scalar_one(),
            "incident_updates": session.execute(text("select count(*) from incident_updates")).scalar_one(),
            "deleted_without_reason": sum(1 for r in rows if r["is_deleted"] and r["deleted_reason"] is None),
        }
    return {"taken_at": datetime.now(timezone.utc).isoformat(), "since": since.isoformat(), "summary_message_ids": sorted(summary_ids),
            "counts": counts, "non_summary_incidents": non_summary}


def compare(before: dict, after: dict) -> dict:
    changed_core, bad_note, note_only = [], [], 0
    for incident_id, old in before["non_summary_incidents"].items():
        new = after["non_summary_incidents"].get(incident_id)
        if new is None:
            changed_core.append(incident_id)
            continue
        if new["core"] != old["core"]:
            changed_core.append(incident_id)
        if new["note"] != old["note"]:
            appended = new["note"][len(old["note"]):] if new["note"].startswith(old["note"]) else None
            if appended is None or CONFIRMATION not in appended:
                bad_note.append(incident_id)
            else:
                note_only += 1
        elif new["updated_at"] != old["updated_at"]:
            changed_core.append(incident_id)
    return {"non_summary_total": len(before["non_summary_incidents"]), "confirmation_note_only": note_only,
            "changed_other_than_note": changed_core, "note_not_a_confirmation_append": bad_note,
            "ok": not changed_core and not bad_note}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--since", type=date.fromisoformat, default=date(2026, 4, 1))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("BEFORE", "AFTER"))
    args = parser.parse_args()
    if args.compare:
        before, after = (json.loads(path.read_text(encoding="utf-8")) for path in args.compare)
        result = compare(before, after)
        print(json.dumps({**result, "before": before["counts"], "after": after["counts"]}, ensure_ascii=False, indent=2, default=str))
        return 0 if result["ok"] else 1
    snapshot = take_snapshot(args.since)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(snapshot, ensure_ascii=False, default=str), encoding="utf-8", newline="\n")
    print(json.dumps(snapshot["counts"], ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
