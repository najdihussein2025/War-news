"""Finish Tier2 for ACCSTUDY stubs that already have extraction+match."""

from __future__ import annotations

from sqlalchemy import text

from app.core.database import SessionLocal
from app.news.services.pipeline.pipeline_llm_workers import (
    run_tier2_detail_fill_for_message,
)


def main() -> None:
    with SessionLocal() as db:
        rows = db.execute(
            text(
                """
                SELECT DISTINCT i.raw_message_id
                FROM incidents i
                JOIN raw_messages rm ON rm.id = i.raw_message_id
                WHERE i.note LIKE 'ACCSTUDY-%'
                  AND i.details_pending IS TRUE
                  AND rm.extraction_result IS NOT NULL
                  AND rm.match_result IS NOT NULL
                ORDER BY i.raw_message_id
                """
            )
        ).fetchall()
    ids = [int(r[0]) for r in rows]
    print(f"tier2_only for {len(ids)} raw_message_ids", flush=True)
    ok = 0
    failed = 0
    for raw_id in ids:
        try:
            updated = run_tier2_detail_fill_for_message(raw_id)
            ok += 1
            print(f"ok raw_message_id={raw_id} updated={updated}", flush=True)
        except Exception as exc:
            failed += 1
            print(f"FAIL raw_message_id={raw_id}: {exc}", flush=True)
    print(f"tier2_only_complete ok={ok} failed={failed}", flush=True)


if __name__ == "__main__":
    main()
