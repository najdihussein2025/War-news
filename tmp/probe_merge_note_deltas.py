#!/usr/bin/env python
"""Probe how historical pipeline_merge note deltas look (read-only)."""
from __future__ import annotations

import json
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
from sqlalchemy import create_engine, text

engine = create_engine("postgresql+psycopg2://postgres:secret@localhost:5432/war_news_dev")

AUTO_MERGE_RE = re.compile(
    r"Automated duplicate merge from raw_message_id=(\d+):\n(.*?)(?=(?:\nAutomated duplicate merge from raw_message_id=|\Z))",
    re.DOTALL,
)


def extract_blocks(note: str | None) -> list[dict]:
    if not note:
        return []
    return [
        {"raw_message_id": int(m.group(1)), "khabar": m.group(2).rstrip("\n")}
        for m in AUTO_MERGE_RE.finditer(note)
    ]


with engine.connect() as c:
    # Mixed human+pollution examples
    mixed = c.execute(
        text(
            """
            SELECT id::text AS id, note
            FROM incidents
            WHERE is_deleted = false
              AND note LIKE '%Automated duplicate merge from raw_message_id=%'
            """
        )
    ).mappings().all()

    print("=== MIXED (human preserved) EXAMPLES ===")
    shown = 0
    for row in mixed:
        note = row["note"] or ""
        cleaned = AUTO_MERGE_RE.sub("", note)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        if cleaned:
            shown += 1
            print(f"\n--- id={row['id']} ---")
            print("BEFORE len", len(note))
            print(note[:600])
            print("AFTER:")
            print(cleaned[:600])
            if shown >= 5:
                break

    # Delta between old_values.note and new_values.note for a few updates
    print("\n=== UPDATE NOTE DELTAS ===")
    rows = c.execute(
        text(
            """
            SELECT iu.id, iu.incident_id::text,
                   iu.old_values->>'note' AS old_note,
                   iu.new_values->>'note' AS new_note
            FROM incident_updates iu
            JOIN incidents i ON i.id = iu.incident_id
            WHERE iu.action = 'pipeline_merge'
              AND i.is_deleted = false
              AND i.note LIKE '%Automated duplicate merge from raw_message_id=%'
              AND iu.new_values ? 'note'
            ORDER BY iu.created_at ASC
            LIMIT 5
            """
        )
    ).mappings().all()
    for row in rows:
        old_blocks = extract_blocks(row["old_note"])
        new_blocks = extract_blocks(row["new_note"])
        # newly added = new_blocks[len(old_blocks):] if append-only
        added = new_blocks[len(old_blocks) :] if len(new_blocks) >= len(old_blocks) else new_blocks
        print(
            json.dumps(
                {
                    "update_id": row["id"],
                    "incident_id": row["incident_id"],
                    "old_block_count": len(old_blocks),
                    "new_block_count": len(new_blocks),
                    "added": added[:2],
                    "old_note_preview": (row["old_note"] or "")[:120],
                    "new_note_preview": (row["new_note"] or "")[:120],
                },
                ensure_ascii=False,
                indent=2,
            )
        )

    # How many updates have old_note / new_note
    stats = c.execute(
        text(
            """
            SELECT
              COUNT(*) AS total,
              COUNT(*) FILTER (WHERE old_values ? 'note') AS old_has_note,
              COUNT(*) FILTER (WHERE new_values ? 'note') AS new_has_note,
              COUNT(*) FILTER (
                WHERE (old_values->>'note') IS DISTINCT FROM (new_values->>'note')
              ) AS note_changed
            FROM incident_updates iu
            WHERE iu.action = 'pipeline_merge'
              AND iu.incident_id IN (
                SELECT id FROM incidents
                WHERE is_deleted = false
                  AND note LIKE '%Automated duplicate merge from raw_message_id=%'
              )
            """
        )
    ).mappings().one()
    print("\n=== UPDATE NOTE FIELD STATS ===")
    print(json.dumps(dict(stats), indent=2, default=str))

    # Recent merges AFTER the forward fix — do they still pollute note?
    recent = c.execute(
        text(
            """
            SELECT
              COUNT(*) FILTER (WHERE new_values ? 'merged_from') AS with_merged_from,
              COUNT(*) FILTER (
                WHERE new_values::text ILIKE '%Automated duplicate merge%'
              ) AS still_auto_in_snapshot,
              MAX(created_at) AS latest
            FROM incident_updates
            WHERE action = 'pipeline_merge'
              AND created_at > now() - interval '2 days'
            """
        )
    ).mappings().one()
    print("\n=== RECENT (2d) pipeline_merge ===")
    print(json.dumps(dict(recent), indent=2, default=str))
