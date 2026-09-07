#!/usr/bin/env python
"""Read-only analysis of historically polluted incident.note values."""
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


def strip_pollution(note: str) -> tuple[str | None, list[dict]]:
    merges: list[dict] = []
    for m in AUTO_MERGE_RE.finditer(note):
        merges.append(
            {
                "raw_message_id": int(m.group(1)),
                "khabar": m.group(2).rstrip("\n"),
            }
        )
    cleaned = AUTO_MERGE_RE.sub("", note)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return (cleaned or None), merges


with engine.connect() as c:
    count = c.execute(
        text(
            """
            SELECT COUNT(*) AS c FROM incidents
            WHERE is_deleted = false
              AND note LIKE '%Automated duplicate merge from raw_message_id=%'
            """
        )
    ).scalar()
    print(f"polluted_count={count}")

    samples = c.execute(
        text(
            """
            SELECT id::text AS id, note, updated_at
            FROM incidents
            WHERE is_deleted = false
              AND note LIKE '%Automated duplicate merge from raw_message_id=%'
            ORDER BY updated_at DESC
            LIMIT 8
            """
        )
    ).mappings().all()

    print("\n=== SAMPLE NOTES (raw) ===")
    only_pollution = 0
    mixed = 0
    multi_merge = 0
    for i, row in enumerate(samples):
        note = row["note"] or ""
        cleaned, merges = strip_pollution(note)
        if cleaned is None:
            only_pollution += 1
        else:
            mixed += 1
        if len(merges) > 1:
            multi_merge += 1
        print(f"\n--- sample {i+1} id={row['id']} merges={len(merges)} cleaned_is_null={cleaned is None} ---")
        print("BEFORE:")
        print(note[:1500])
        print("AFTER:")
        print(repr(cleaned) if cleaned is None else cleaned[:800])
        print("MERGED_FROM candidates:")
        print(json.dumps(merges[:3], ensure_ascii=False, indent=2)[:800])

    # Full-population classification
    all_rows = c.execute(
        text(
            """
            SELECT id::text AS id, note
            FROM incidents
            WHERE is_deleted = false
              AND note LIKE '%Automated duplicate merge from raw_message_id=%'
            """
        )
    ).mappings().all()

    only = mixed_n = multi = total_merges = 0
    residual_auto = 0
    for row in all_rows:
        cleaned, merges = strip_pollution(row["note"] or "")
        total_merges += len(merges)
        if len(merges) > 1:
            multi += 1
        if cleaned is None:
            only += 1
        else:
            mixed_n += 1
            if "Automated duplicate merge" in cleaned:
                residual_auto += 1

    print("\n=== POPULATION CLASSIFICATION ===")
    print(
        json.dumps(
            {
                "polluted": len(all_rows),
                "only_pollution_null_after": only,
                "mixed_human_preserved": mixed_n,
                "multi_merge_blocks": multi,
                "total_merge_blocks_extracted": total_merges,
                "residual_auto_after_strip": residual_auto,
            },
            indent=2,
        )
    )

    cov = c.execute(
        text(
            """
            WITH polluted AS (
              SELECT id FROM incidents
              WHERE is_deleted = false
                AND note LIKE '%Automated duplicate merge from raw_message_id=%'
            )
            SELECT
              (SELECT COUNT(*) FROM polluted) AS polluted_incidents,
              COUNT(*) AS pipeline_merge_rows_for_polluted,
              COUNT(*) FILTER (WHERE new_values ? 'merged_from') AS already_have_merged_from,
              COUNT(*) FILTER (WHERE new_values ? 'note') AS have_note_in_new_values,
              COUNT(*) FILTER (
                WHERE new_values::text ILIKE '%Automated duplicate merge%'
              ) AS new_values_contain_auto_text
            FROM incident_updates iu
            WHERE iu.action = 'pipeline_merge'
              AND iu.incident_id IN (SELECT id FROM polluted)
            """
        )
    ).mappings().one()
    print("\n=== MERGE COVERAGE FOR POLLUTED ===")
    print(json.dumps(dict(cov), ensure_ascii=False, indent=2, default=str))

    # Do polluted incidents always have a pipeline_merge row?
    orphan = c.execute(
        text(
            """
            SELECT COUNT(*) AS polluted_without_pipeline_merge
            FROM incidents i
            WHERE i.is_deleted = false
              AND i.note LIKE '%Automated duplicate merge from raw_message_id=%'
              AND NOT EXISTS (
                SELECT 1 FROM incident_updates iu
                WHERE iu.incident_id = i.id AND iu.action = 'pipeline_merge'
              )
            """
        )
    ).scalar()
    print(f"\npolluted_without_any_pipeline_merge={orphan}")

    # Sample update new_values structure
    upd = c.execute(
        text(
            """
            SELECT iu.id, iu.incident_id::text, iu.new_values, iu.created_at
            FROM incident_updates iu
            JOIN incidents i ON i.id = iu.incident_id
            WHERE iu.action = 'pipeline_merge'
              AND i.is_deleted = false
              AND i.note LIKE '%Automated duplicate merge from raw_message_id=%'
            ORDER BY iu.created_at DESC
            LIMIT 3
            """
        )
    ).mappings().all()
    print("\n=== SAMPLE pipeline_merge new_values ===")
    for row in upd:
        nv = row["new_values"] or {}
        print(
            json.dumps(
                {
                    "update_id": row["id"],
                    "incident_id": row["incident_id"],
                    "keys": list(nv.keys()),
                    "has_merged_from": "merged_from" in nv,
                    "note_preview": str(nv.get("note"))[:300] if "note" in nv else None,
                    "merged_from": nv.get("merged_from"),
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
