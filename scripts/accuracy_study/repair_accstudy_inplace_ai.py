"""In-place AI repair for ACCSTUDY-001/004 (no excel rematerialize/delete)."""

from __future__ import annotations

from sqlalchemy import select

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401
from app.core.database import SessionLocal
from app.llm.dtos import ExtractionResult
from app.news.models import Incident, MessageStatus, RawMessage
from app.news.repositories.condition_repository import ConditionRepository
from app.news.repositories.village_repository import VillageRepository
from app.news.services.matching.matching_service import MatchingService
from app.news.services.pipeline.pipeline_llm_workers import (
    run_tier1_extraction_for_message,
    run_tier2_detail_fill_for_message,
)

TARGET_NOTES = ("ACCSTUDY-001", "ACCSTUDY-004")


def main() -> None:
    raw_ids: list[int] = []
    with SessionLocal() as db:
        for note in TARGET_NOTES:
            incident = db.scalars(select(Incident).where(Incident.note == note)).first()
            if incident is None or incident.raw_message_id is None:
                print(f"{note}: missing incident")
                continue
            raw = db.get(RawMessage, incident.raw_message_id)
            if raw is None:
                print(f"{note}: missing raw")
                continue
            raw.extraction_result = None
            raw.match_result = None
            raw.status = MessageStatus.parsed
            raw.error_message = None
            raw.extraction_retry_count = 0
            incident.details_pending = True
            db.add(raw)
            db.add(incident)
            raw_ids.append(raw.id)
            print(f"queued {note} raw={raw.id} incident={incident.id}")
        db.commit()

    for raw_id in raw_ids:
        print(f"tier1 raw={raw_id}")
        run_tier1_extraction_for_message(raw_id)
        with SessionLocal() as db:
            raw = db.get(RawMessage, raw_id)
            if raw is None or raw.extraction_result is None:
                print(f"tier1 failed raw={raw_id}")
                continue
            if raw.status != MessageStatus.parsed:
                raw.status = MessageStatus.parsed
                db.add(raw)
                db.commit()
            matcher = MatchingService(
                VillageRepository(db), ConditionRepository(db)
            )
            dto = ExtractionResult.model_validate(raw.extraction_result)
            result = matcher.match(dto)
            raw.match_result = result.model_dump(mode="json")
            db.add(raw)

            # Fill village/condition on existing excel incident rows.
            for incident in db.scalars(
                select(Incident).where(Incident.raw_message_id == raw_id)
            ).all():
                for vm in result.village_matches:
                    status = getattr(
                        vm.village_match_status, "value", vm.village_match_status
                    )
                    if status in {"matched", "matched_low_confidence"} and isinstance(
                        vm.matched_village_id, int
                    ):
                        incident.village_id = vm.matched_village_id
                        if getattr(vm, "alias_matched", False):
                            text = (vm.raw_village_text or "").strip()
                            if text:
                                incident.village_display_name = text
                        break
                if result.matched_condition_id is not None:
                    incident.condition_id = result.matched_condition_id
                db.add(incident)
            db.commit()
            print(
                f"matched raw={raw_id} villages="
                f"{[(vm.raw_village_text, vm.matched_village_id) for vm in result.village_matches]}"
            )

        print(f"tier2 raw={raw_id}")
        updated = run_tier2_detail_fill_for_message(raw_id)
        print(f"tier2 updated={updated}")

    with SessionLocal() as db:
        for note in TARGET_NOTES:
            incident = db.scalars(select(Incident).where(Incident.note == note)).first()
            if incident is None:
                print(f"{note}: gone")
                continue
            from app.news.models import IncidentDetail

            detail = db.scalar(
                select(IncidentDetail).where(IncidentDetail.incident_id == incident.id)
            )
            print(
                {
                    "note": note,
                    "id": str(incident.id),
                    "village_id": incident.village_id,
                    "condition_id": incident.condition_id,
                    "car": getattr(detail, "car", None),
                    "cara_d": getattr(detail, "cara_d", None),
                    "cara_i": getattr(detail, "cara_i", None),
                    "card": getattr(detail, "card", None),
                    "cari": getattr(detail, "cari", None),
                }
            )


if __name__ == "__main__":
    main()
