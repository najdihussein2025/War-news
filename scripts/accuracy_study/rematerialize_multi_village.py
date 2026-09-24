"""Rematerialize ACCSTUDY multi-village messages after condition fallback fix."""

from __future__ import annotations

from sqlalchemy import select, text

from app.core.database import SessionLocal
from app.news.models import Incident, MessageStatus, RawMessage
from app.news.repositories.incident_repository import IncidentRepository
from app.news.services.dedup.dedup_matching_service import DedupMatchingService
from app.news.services.incidents.imported_incident_enrichment import (
    _apply_import_metadata,
)
from app.news.services.materialization.incident_materialization_service import (
    IncidentMaterializationService,
)


def main() -> None:
    with SessionLocal() as db:
        rows = db.execute(
            text(
                """
                SELECT DISTINCT rm.id, rm.raw_payload->'import_metadata'->>'note' AS note
                FROM raw_messages rm
                WHERE (rm.raw_payload->>'origin') = 'incident_excel_import'
                  AND (
                    rm.raw_payload->'import_metadata'->>'note' LIKE 'ACCSTUDY-%'
                    OR EXISTS (
                        SELECT 1 FROM incidents i
                        WHERE i.raw_message_id = rm.id AND i.note LIKE 'ACCSTUDY-%'
                    )
                  )
                  AND jsonb_array_length(COALESCE(rm.match_result->'village_matches','[]'::jsonb)) > 1
                ORDER BY rm.id
                """
            )
        ).fetchall()

    print(f"rematerializing {len(rows)} multi-match ACCSTUDY raw messages", flush=True)
    for raw_id, note in rows:
        with SessionLocal() as db:
            rm = db.get(RawMessage, raw_id)
            if rm is None:
                continue
            meta = dict((rm.raw_payload or {}).get("import_metadata") or {})
            if note and not meta.get("note"):
                meta["note"] = note
                payload = dict(rm.raw_payload or {})
                payload["import_metadata"] = meta
                rm.raw_payload = payload
            # Soft-delete existing rows so hashes do not block re-insert.
            for incident in db.scalars(
                select(Incident).where(Incident.raw_message_id == raw_id)
            ).all():
                incident.is_deleted = True
                db.add(incident)
            rm.status = MessageStatus.parsed
            db.add(rm)
            db.commit()

            rm = db.get(RawMessage, raw_id)
            svc = IncidentMaterializationService(
                db,
                dedup_service=DedupMatchingService(
                    incident_repository=IncidentRepository(db)
                ),
            )
            created = svc.materialize(rm)
            if meta:
                _apply_import_metadata(db, raw_id, meta)
            db.commit()
            print(
                f"raw={raw_id} note={meta.get('note')} created={len(created)} "
                f"inserted={svc.stats.inserted} skipped_ineligible={svc.stats.skipped_ineligible} "
                f"story={getattr(created[0], 'story_group_id', None) if created else None}",
                flush=True,
            )

    print("done", flush=True)


if __name__ == "__main__":
    main()
