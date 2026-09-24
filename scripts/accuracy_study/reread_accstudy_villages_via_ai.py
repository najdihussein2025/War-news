"""Re-run AI enrichment (Tier1 → match → Tier2) for specific ACCSTUDY rows.

Resets extraction/match so the LLM re-reads the news text; does not SQL-patch
village names. Aliases in village_location_aliases still apply at match time.
"""

from __future__ import annotations

from sqlalchemy import select

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401
from app.core.database import SessionLocal
from app.news.models import Incident, MessageStatus, RawMessage
from app.news.services.incidents.imported_incident_enrichment import (
    enrich_imported_incidents,
)

TARGET_NOTES = ("ACCSTUDY-001", "ACCSTUDY-004")


def main() -> None:
    with SessionLocal() as db:
        incidents = list(
            db.scalars(
                select(Incident).where(Incident.note.in_(TARGET_NOTES))
            ).all()
        )
        if not incidents:
            raise SystemExit(f"No incidents found for {TARGET_NOTES}")

        raw_ids: list[int] = []
        for incident in incidents:
            if incident.raw_message_id is None:
                continue
            raw = db.get(RawMessage, incident.raw_message_id)
            if raw is None:
                continue

            # Clear AI outputs so Tier1 actually re-runs.
            raw.extraction_result = None
            raw.match_result = None
            raw.status = MessageStatus.parsed
            raw.error_message = None
            raw.extraction_retry_count = 0
            db.add(raw)

            # Clear structured village so the pipeline must refill it.
            incident.village_id = None
            incident.village_display_name = None
            incident.details_pending = True
            db.add(incident)
            raw_ids.append(raw.id)
            print(
                f"queued note={incident.note} raw_message_id={raw.id} "
                f"incident_id={incident.id}"
            )

        db.commit()

    print(f"running enrich_imported_incidents for {raw_ids}")
    enrich_imported_incidents(raw_ids)

    with SessionLocal() as db:
        for note in TARGET_NOTES:
            incident = db.scalars(
                select(Incident).where(Incident.note == note)
            ).first()
            if incident is None:
                print(f"{note}: missing")
                continue
            raw = db.get(RawMessage, incident.raw_message_id)
            village_ext = None
            if raw and isinstance(raw.extraction_result, dict):
                village_ext = raw.extraction_result.get("village")
            match_villages = None
            if raw and isinstance(raw.match_result, dict):
                match_villages = [
                    {
                        "raw": vm.get("raw_village_text"),
                        "id": vm.get("matched_village_id"),
                        "status": vm.get("village_match_status"),
                        "alias": vm.get("alias_matched"),
                    }
                    for vm in (raw.match_result.get("village_matches") or [])
                ]
            print(
                {
                    "note": note,
                    "village_id": incident.village_id,
                    "village_display_name": incident.village_display_name,
                    "raw_status": getattr(raw, "status", None),
                    "extracted_village": village_ext,
                    "match_villages": match_villages,
                    "details_pending": incident.details_pending,
                }
            )


if __name__ == "__main__":
    main()
