"""Repair ACCSTUDY-001/004 after a failed re-read left them unmatched."""

from __future__ import annotations

from copy import deepcopy

from pydantic import ValidationError
from sqlalchemy import select

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401
from app.core.database import SessionLocal
from app.core.text_normalization import normalize_arabic_text
from app.llm.dtos import ExtractionResult
from app.news.models import Incident, IncidentDetail, MessageStatus, RawMessage
from app.news.repositories.condition_repository import ConditionRepository
from app.news.repositories.village_repository import VillageRepository
from app.news.services.extraction.tier2_detail_fill_service import Tier2DetailFillService
from app.news.services.incident_details.category_mapper import (
    compute_rollups,
    map_categories,
)
from app.news.services.matching.matching_service import MatchingService
from app.api.factories.action_factory import build_extraction_classifier

TARGET_NOTES = ("ACCSTUDY-001", "ACCSTUDY-004")


def main() -> None:
    db = SessionLocal()
    try:
        matcher = MatchingService(VillageRepository(db), ConditionRepository(db))
        classifier = build_extraction_classifier()
        tier2 = Tier2DetailFillService(db, classifier)

        for note in TARGET_NOTES:
            incident = db.scalars(select(Incident).where(Incident.note == note)).first()
            if incident is None or incident.raw_message_id is None:
                print(f"{note}: missing")
                continue
            raw = db.get(RawMessage, incident.raw_message_id)
            if raw is None or not isinstance(raw.extraction_result, dict):
                print(f"{note}: no extraction")
                continue

            extraction = deepcopy(raw.extraction_result)
            villages = extraction.get("village")
            if not villages:
                # Recover from khabar via aliases already in DB.
                khabar = incident.khabar or raw.raw_text or ""
                for token, acs in (("دبل", 72281), ("الجبين", 62292)):
                    if token in normalize_arabic_text(khabar) or token in khabar:
                        extraction["village"] = [token]
                        extraction["village_roles"] = [
                            {"village": token, "role": "target"}
                        ]
                        break
                raw.extraction_result = extraction
                db.add(raw)
                db.flush()

            try:
                dto = ExtractionResult.model_validate(extraction)
            except ValidationError as exc:
                print(f"{note}: invalid extraction {exc}")
                continue

            result = matcher.match(dto)
            raw.match_result = result.model_dump(mode="json")
            raw.status = MessageStatus.materialized
            raw.error_message = None
            db.add(raw)

            chosen = None
            display = None
            for vm in result.village_matches:
                status = getattr(vm.village_match_status, "value", vm.village_match_status)
                if status in {"matched", "matched_low_confidence"} and isinstance(
                    vm.matched_village_id, int
                ):
                    chosen = vm.matched_village_id
                    if getattr(vm, "alias_matched", False):
                        display = (vm.raw_village_text or "").strip() or None
                    break
            if chosen is not None:
                incident.village_id = chosen
                if display:
                    incident.village_display_name = display
            if result.matched_condition_id is not None:
                incident.condition_id = result.matched_condition_id

            # Apply category mapping (vehicles anonymous fields) from extraction.
            categories = dto.categories or {}
            mapped = map_categories(categories)
            root = dto.casualties
            total_d, total_i = compute_rollups(mapped, root)
            if total_d is not None:
                incident.total_deaths = total_d
            if total_i is not None:
                incident.total_injuries = total_i
            if root and root.deaths is not None and incident.deaths is None:
                incident.deaths = root.deaths
            if root and root.injuries is not None and incident.injuries is None:
                incident.injuries = root.injuries

            detail = db.scalar(
                select(IncidentDetail).where(IncidentDetail.incident_id == incident.id)
            )
            if detail is None:
                detail = IncidentDetail(incident_id=incident.id)
                db.add(detail)
            for key, value in mapped.items():
                if hasattr(detail, key):
                    setattr(detail, key, value)

            incident.details_pending = False
            db.add(incident)
            print(
                {
                    "note": note,
                    "incident_id": str(incident.id),
                    "village_id": incident.village_id,
                    "condition_id": incident.condition_id,
                    "car": mapped.get("car"),
                    "cara_d": mapped.get("cara_d"),
                    "cara_i": mapped.get("cara_i"),
                    "card": mapped.get("card"),
                    "cari": mapped.get("cari"),
                }
            )

        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
