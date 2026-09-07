#!/usr/bin/env python
"""Historical cleanup: strip automated merge pollution from incident.note.

Forward-only fix (be91e0d) already stops new pollution and writes structured
``merged_from`` on ``incident_updates``. This script migrates *historical*
rows:

1. Strip every ``Automated duplicate merge from raw_message_id=...`` block
   from ``incidents.note``, preserving any remaining human / origin-village
   text. Pure-pollution notes become NULL (not empty string).
2. For each existing ``pipeline_merge`` ``incident_updates`` row on those
   incidents, derive the merge that this update introduced (note delta) and
   add ``new_values["merged_from"] = {raw_message_id, channel, khabar}``.
3. Strip the same pollution from ``old_values["note"]`` / ``new_values["note"]``
   snapshots so audit history matches the cleaned live note.

STANDING CONVENTION: do not run ``--apply`` against production without Najdi
review. Default mode is dry-run / read-only.

Usage:
  python scripts/review/cleanup_historical_merge_note_pollution.py
  python scripts/review/cleanup_historical_merge_note_pollution.py --examples 5
  python scripts/review/cleanup_historical_merge_note_pollution.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# Default matches local docker-compose Postgres published on localhost.
# Inside the backend container, set DATABASE_URL to the compose service DSN
# (postgresql+psycopg2://postgres:secret@db:5432/war_news_dev) or rely on .env.
DEFAULT_DATABASE_URL = "postgresql+psycopg2://postgres:secret@localhost:5432/war_news_dev"


def _session() -> Session:
    url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    # Host-side runs cannot resolve Docker DNS name `db`.
    if "@db:" in url:
        url = url.replace("@db:", "@localhost:")
    engine = create_engine(url)
    return sessionmaker(bind=engine)()

AUTO_MERGE_RE = re.compile(
    r"Automated duplicate merge from raw_message_id=(\d+):\n"
    r"(.*?)(?=(?:\nAutomated duplicate merge from raw_message_id=|\Z))",
    re.DOTALL,
)

POLLUTION_LIKE = "%Automated duplicate merge from raw_message_id=%"


def extract_blocks(note: str | None) -> list[dict[str, Any]]:
    if not note:
        return []
    return [
        {
            "raw_message_id": int(match.group(1)),
            "khabar": match.group(2).rstrip("\n"),
        }
        for match in AUTO_MERGE_RE.finditer(note)
    ]


def strip_pollution(note: str | None) -> str | None:
    if note is None:
        return None
    cleaned = AUTO_MERGE_RE.sub("", note)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned or None


def added_merge_block(old_note: str | None, new_note: str | None) -> dict[str, Any] | None:
    """Return the merge block newly appended on this update (append-only history)."""
    old_blocks = extract_blocks(old_note)
    new_blocks = extract_blocks(new_note)
    if len(new_blocks) > len(old_blocks):
        return new_blocks[len(old_blocks)]
    if new_blocks and not old_blocks:
        return new_blocks[0]
    if new_blocks and len(new_blocks) == len(old_blocks):
        # Same count but note changed — use the last block as best effort.
        return new_blocks[-1]
    return None


def clean_note_in_values(values: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(values, dict) or "note" not in values:
        return values
    updated = deepcopy(values)
    updated["note"] = strip_pollution(values.get("note") if isinstance(values.get("note"), str) else None)
    return updated


def fetch_channel_map(db, raw_message_ids: set[int]) -> dict[int, str | None]:
    if not raw_message_ids:
        return {}
    rows = db.execute(
        text(
            """
            SELECT id,
                   COALESCE(
                     NULLIF(source_name, ''),
                     NULLIF(origin_account, ''),
                     NULLIF(source_platform, '')
                   ) AS channel
            FROM raw_messages
            WHERE id = ANY(:ids)
            """
        ),
        {"ids": list(raw_message_ids)},
    ).mappings().all()
    return {int(row["id"]): row["channel"] for row in rows}


def plan_cleanup(db) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    incidents = db.execute(
        text(
            """
            SELECT id::text AS id, note
            FROM incidents
            WHERE is_deleted = false
              AND note LIKE :pattern
            ORDER BY updated_at DESC NULLS LAST
            """
        ),
        {"pattern": POLLUTION_LIKE},
    ).mappings().all()

    incident_plans: list[dict[str, Any]] = []
    for row in incidents:
        before = row["note"]
        after = strip_pollution(before)
        blocks = extract_blocks(before)
        incident_plans.append(
            {
                "id": row["id"],
                "before": before,
                "after": after,
                "blocks_removed": len(blocks),
                "becomes_null": after is None,
            }
        )

    updates = db.execute(
        text(
            """
            SELECT iu.id,
                   iu.incident_id::text AS incident_id,
                   iu.old_values,
                   iu.new_values
            FROM incident_updates iu
            WHERE iu.action = 'pipeline_merge'
              AND iu.incident_id IN (
                SELECT id FROM incidents
                WHERE is_deleted = false
                  AND note LIKE :pattern
              )
            ORDER BY iu.created_at ASC, iu.id ASC
            """
        ),
        {"pattern": POLLUTION_LIKE},
    ).mappings().all()

    raw_ids: set[int] = set()
    provisional: list[dict[str, Any]] = []
    for row in updates:
        old_values = row["old_values"] or {}
        new_values = row["new_values"] or {}
        if new_values.get("merged_from"):
            provisional.append(
                {
                    "id": row["id"],
                    "incident_id": row["incident_id"],
                    "skip_reason": "already_has_merged_from",
                    "merged_from": new_values["merged_from"],
                    "old_values": old_values,
                    "new_values": new_values,
                }
            )
            continue
        old_note = old_values.get("note") if isinstance(old_values.get("note"), str) else None
        new_note = new_values.get("note") if isinstance(new_values.get("note"), str) else None
        block = added_merge_block(old_note, new_note)
        if block is None:
            provisional.append(
                {
                    "id": row["id"],
                    "incident_id": row["incident_id"],
                    "skip_reason": "no_auto_merge_block_in_note_delta",
                    "merged_from": None,
                    "old_values": old_values,
                    "new_values": new_values,
                }
            )
            continue
        raw_ids.add(int(block["raw_message_id"]))
        provisional.append(
            {
                "id": row["id"],
                "incident_id": row["incident_id"],
                "skip_reason": None,
                "block": block,
                "old_values": old_values,
                "new_values": new_values,
            }
        )

    channels = fetch_channel_map(db, raw_ids)
    update_plans: list[dict[str, Any]] = []
    for item in provisional:
        if item.get("skip_reason"):
            update_plans.append(item)
            continue
        block = item["block"]
        merged_from = {
            "raw_message_id": int(block["raw_message_id"]),
            "channel": channels.get(int(block["raw_message_id"])),
            "khabar": block["khabar"],
        }
        cleaned_old = clean_note_in_values(item["old_values"])
        cleaned_new = clean_note_in_values(item["new_values"]) or {}
        cleaned_new = {**cleaned_new, "merged_from": merged_from}
        update_plans.append(
            {
                "id": item["id"],
                "incident_id": item["incident_id"],
                "skip_reason": None,
                "merged_from": merged_from,
                "old_values": cleaned_old,
                "new_values": cleaned_new,
                "before_note": (item["new_values"] or {}).get("note"),
                "after_note": cleaned_new.get("note"),
            }
        )
    return incident_plans, update_plans


def print_summary(incident_plans: list[dict[str, Any]], update_plans: list[dict[str, Any]]) -> None:
    become_null = sum(1 for p in incident_plans if p["becomes_null"])
    preserve = len(incident_plans) - become_null
    skip_already = sum(1 for p in update_plans if p.get("skip_reason") == "already_has_merged_from")
    skip_no_block = sum(
        1 for p in update_plans if p.get("skip_reason") == "no_auto_merge_block_in_note_delta"
    )
    will_backfill = sum(1 for p in update_plans if p.get("skip_reason") is None)
    print("=== SCOPE ===")
    print(f"polluted_incidents={len(incident_plans)}")
    print(f"incidents_note_becomes_null={become_null}")
    print(f"incidents_note_preserves_human_text={preserve}")
    print(f"pipeline_merge_updates_in_scope={len(update_plans)}")
    print(f"updates_receiving_merged_from={will_backfill}")
    print(f"updates_skipped_already_has_merged_from={skip_already}")
    print(f"updates_skipped_no_note_delta_block={skip_no_block}")


def print_examples(
    incident_plans: list[dict[str, Any]],
    update_plans: list[dict[str, Any]],
    limit: int,
) -> None:
    print(f"\n=== DRY-RUN EXAMPLES (up to {limit}) ===")
    # Prefer a mix: at least one preserved-human and some null-after.
    mixed = [p for p in incident_plans if not p["becomes_null"]]
    only = [p for p in incident_plans if p["becomes_null"]]
    chosen: list[dict[str, Any]] = []
    for pool in (mixed, only):
        for plan in pool:
            if plan not in chosen:
                chosen.append(plan)
            if len(chosen) >= limit:
                break
        if len(chosen) >= limit:
            break

    updates_by_incident: dict[str, list[dict[str, Any]]] = {}
    for upd in update_plans:
        if upd.get("skip_reason") is None:
            updates_by_incident.setdefault(upd["incident_id"], []).append(upd)

    for idx, plan in enumerate(chosen, start=1):
        sample_updates = updates_by_incident.get(plan["id"], [])[:2]
        print(f"\n--- example {idx} incident_id={plan['id']} ---")
        print(f"blocks_removed={plan['blocks_removed']} becomes_null={plan['becomes_null']}")
        print("BEFORE note:")
        print(plan["before"][:900] if plan["before"] else repr(plan["before"]))
        print("AFTER note:")
        print(repr(plan["after"]) if plan["after"] is None else plan["after"][:500])
        print("merged_from backfill sample(s) for this incident's pipeline_merge rows:")
        if not sample_updates:
            print("  (no pipeline_merge rows needing backfill)")
        for upd in sample_updates:
            print(
                json.dumps(
                    {
                        "update_id": upd["id"],
                        "merged_from": upd["merged_from"],
                        "snapshot_note_after": upd.get("after_note"),
                    },
                    ensure_ascii=False,
                    indent=2,
                )[:1200]
            )


def apply_cleanup(
    db,
    incident_plans: list[dict[str, Any]],
    update_plans: list[dict[str, Any]],
) -> None:
    for plan in incident_plans:
        db.execute(
            text(
                """
                UPDATE incidents
                SET note = :note, updated_at = now()
                WHERE id = CAST(:id AS uuid)
                  AND is_deleted = false
                  AND note LIKE :pattern
                """
            ),
            {
                "id": plan["id"],
                "note": plan["after"],
                "pattern": POLLUTION_LIKE,
            },
        )

    for plan in update_plans:
        if plan.get("skip_reason") is not None:
            continue
        db.execute(
            text(
                """
                UPDATE incident_updates
                SET old_values = CAST(:old_values AS jsonb),
                    new_values = CAST(:new_values AS jsonb)
                WHERE id = :id
                  AND action = 'pipeline_merge'
                  AND NOT (new_values ? 'merged_from')
                """
            ),
            {
                "id": plan["id"],
                "old_values": json.dumps(plan["old_values"], ensure_ascii=False),
                "new_values": json.dumps(plan["new_values"], ensure_ascii=False),
            },
        )
    db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run or apply historical cleanup of automated merge text in "
            "incident.note, migrating provenance into incident_updates.merged_from."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist changes. Omit for dry-run (default).",
    )
    parser.add_argument(
        "--examples",
        type=int,
        default=5,
        help="How many before/after examples to print in dry-run (default 5).",
    )
    args = parser.parse_args()

    db = _session()
    try:
        incident_plans, update_plans = plan_cleanup(db)
        print_summary(incident_plans, update_plans)
        print_examples(incident_plans, update_plans, limit=max(1, args.examples))

        if not args.apply:
            print(
                "\nDry run only — no database writes. "
                "Re-run with --apply after Najdi review to persist."
            )
            return

        apply_cleanup(db, incident_plans, update_plans)
        print(
            f"\nApplied: incidents_updated={len(incident_plans)} "
            f"updates_backfilled="
            f"{sum(1 for p in update_plans if p.get('skip_reason') is None)}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
