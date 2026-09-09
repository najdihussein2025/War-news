#!/usr/bin/env python
"""Read-only report of relevance signals on materialized incidents.

Reports the 2026-09-09 Sin el-Fil incidents, then summarizes relevance
classifications for all active auto-processed incidents.

Usage:
  python scripts/review/inspect_relevance_sample.py
  python scripts/review/inspect_relevance_sample.py --examples 5
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_DATABASE_URL = "postgresql+psycopg2://postgres:secret@localhost:5432/war_news_dev"


def _session() -> Session:
    url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    if "@db:" in url:
        url = url.replace("@db:", "@localhost:")
    return sessionmaker(bind=create_engine(url))()


def _json_object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _confidence_bucket(value: Any) -> str:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return "(missing/invalid)"
    if confidence < 0.5:
        return "<0.5"
    if confidence < 0.7:
        return "0.5-<0.7"
    if confidence < 0.9:
        return "0.7-<0.9"
    return ">=0.9"


def print_sin_el_fil_incidents(db: Session) -> None:
    rows = db.execute(
        text(
            """
            SELECT
              i.id AS incident_id,
              i.event_date,
              i.event_time,
              i.verification_status,
              i.duplicate_flag,
              i.khabar,
              v.ref_name_ar,
              v.ref_name_en,
              v.cad_name,
              r.filter_result,
              r.low_confidence_relevance,
              r.raw_text
            FROM incidents i
            JOIN villages v ON v.id = i.village_id
            LEFT JOIN raw_messages r ON r.id = i.raw_message_id
            WHERE i.is_deleted = false
              AND i.event_date = DATE '2026-09-09'
              AND (
                trim(v.ref_name_ar) = 'سن الفيل'
                OR lower(replace(trim(v.ref_name_en), '-', ' '))
                     IN ('sin el fil', 'sinn el fil')
                OR lower(replace(trim(v.cad_name), '-', ' '))
                     IN ('sin el fil', 'sinn el fil')
              )
            ORDER BY i.event_time NULLS LAST, i.created_at, i.id
            """
        )
    ).mappings().all()

    print("=== Part 1: Sin el-Fil incidents on 2026-09-09 ===")
    print(f"matching active incidents: {len(rows)}")
    for row in rows:
        print(
            f"\nincident_id: {row['incident_id']}\n"
            f"event: {row['event_date']} {row['event_time']}\n"
            f"village: ref_name_ar={row['ref_name_ar']!r}, "
            f"ref_name_en={row['ref_name_en']!r}, cad_name={row['cad_name']!r}\n"
            f"verification_status: {row['verification_status']}\n"
            f"duplicate_flag: {row['duplicate_flag']}\n"
            f"khabar:\n{row['khabar']}\n"
            f"raw_text:\n{row['raw_text']}\n"
            "filter_result:\n"
            f"{json.dumps(row['filter_result'], ensure_ascii=False, indent=2, default=str)}\n"
            f"low_confidence_relevance: {row['low_confidence_relevance']}"
        )


def print_auto_processed_summary(db: Session, example_count: int) -> None:
    counts = db.execute(
        text(
            """
            SELECT
              count(*) AS total,
              count(*) FILTER (
                WHERE r.filter_result->>'verdict' = 'uncertain'
              ) AS uncertain,
              count(*) FILTER (
                WHERE r.low_confidence_relevance = true
                   OR r.filter_result->>'needs_review' = 'true'
              ) AS borderline
            FROM incidents i
            LEFT JOIN raw_messages r ON r.id = i.raw_message_id
            WHERE i.is_deleted = false
              AND i.verification_status = 'auto_processed'
            """
        )
    ).mappings().one()

    borderline_rows = db.execute(
        text(
            """
            SELECT
              i.id AS incident_id,
              i.event_date,
              i.event_time,
              COALESCE(v.ref_name_en, v.cad_name, v.ref_name_ar) AS village,
              COALESCE(c.action_en, c.action_ar) AS condition,
              i.khabar,
              r.filter_result,
              r.low_confidence_relevance
            FROM incidents i
            JOIN raw_messages r ON r.id = i.raw_message_id
            LEFT JOIN villages v ON v.id = i.village_id
            LEFT JOIN conditions c ON c.id = i.condition_id
            WHERE i.is_deleted = false
              AND i.verification_status = 'auto_processed'
              AND (
                r.low_confidence_relevance = true
                OR r.filter_result->>'needs_review' = 'true'
              )
            ORDER BY i.event_date DESC, i.event_time DESC NULLS LAST, i.created_at DESC
            """
        )
    ).mappings().all()

    buckets = Counter(
        _confidence_bucket(_json_object(row["filter_result"]).get("confidence"))
        for row in borderline_rows
    )
    print("\n=== Part 2: active auto_processed relevance summary ===")
    print(f"total active auto_processed incidents: {counts['total']}")
    print(f"uncertain verdict: {counts['uncertain']}")
    print(f"borderline relevant / needs review: {counts['borderline']}")
    fraction = (counts["borderline"] / counts["total"]) if counts["total"] else 0.0
    print(f"borderline fraction: {fraction:.2%}")

    print("\nConfidence distribution for borderline group:")
    for bucket in ("<0.5", "0.5-<0.7", "0.7-<0.9", ">=0.9", "(missing/invalid)"):
        print(f"  {bucket}: {buckets[bucket]}")

    shown = borderline_rows[:example_count]
    print(f"\nExamples from borderline group (showing {len(shown)}):")
    for row in shown:
        filter_result = _json_object(row["filter_result"])
        print(
            f"\nincident_id: {row['incident_id']}\n"
            f"event: {row['event_date']} {row['event_time']}\n"
            f"village: {row['village']}\n"
            f"condition: {row['condition']}\n"
            f"confidence: {filter_result.get('confidence')!r}\n"
            f"low_confidence_relevance: {row['low_confidence_relevance']}\n"
            f"needs_review: {filter_result.get('needs_review')!r}\n"
            f"reasoning: {filter_result.get('reasoning')}\n"
            f"khabar:\n{row['khabar']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only relevance report for materialized incidents."
    )
    parser.add_argument("--examples", type=int, default=10)
    args = parser.parse_args()

    db = _session()
    try:
        db.execute(text("SET TRANSACTION READ ONLY"))
        print_sin_el_fil_incidents(db)
        print_auto_processed_summary(db, example_count=max(5, min(10, args.examples)))
    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    main()
