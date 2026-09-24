"""Resume Tier2 enrichment for pending ACCSTUDY import stubs."""

from __future__ import annotations

from sqlalchemy import text

from app.core.database import SessionLocal
from app.news.services.incidents.imported_incident_enrichment import (
    enrich_imported_incidents,
)


def main() -> None:
    with SessionLocal() as db:
        rows = db.execute(
            text(
                """
                SELECT DISTINCT i.raw_message_id
                FROM incidents i
                WHERE i.note LIKE 'ACCSTUDY-%'
                  AND i.details_pending IS TRUE
                  AND i.raw_message_id IS NOT NULL
                ORDER BY i.raw_message_id
                """
            )
        ).fetchall()
    ids = [int(r[0]) for r in rows]
    print(f"resuming enrichment for {len(ids)} raw_message_ids", flush=True)
    enrich_imported_incidents(ids)
    print("resume_complete", flush=True)


if __name__ == "__main__":
    main()
