"""Repair one already-extracted heading/list bulletin without another LLM call.

Usage:
    python -m scripts.fixes.reprocess_sectioned_raw_message RAW_ID --apply

The command is intentionally narrow: it refuses messages that do not contain
at least two recognized action sections. Existing rows owned by the raw
message are soft-deleted, erroneous story-merge audit links sourced from the
message are removed, and corrected rows are materialized transactionally.
"""

from __future__ import annotations

import argparse

from sqlalchemy import delete, select

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401
from app.core.database import SessionLocal
from app.llm.dtos import ExtractionResult, VillageRole
from app.llm.services.ollama_extraction_service import OllamaExtractionService
from app.llm.services.sectioned_bulletin import recover_sectioned_sub_events
from app.news.models import Incident, IncidentUpdate, RawMessage
from app.news.repositories.condition_repository import ConditionRepository
from app.news.repositories.incident_repository import IncidentRepository
from app.news.services.incidents.soft_delete import soft_delete_incident
from app.news.repositories.village_repository import VillageRepository
from app.news.services.dedup.dedup_matching_service import DedupMatchingService
from app.news.services.matching.matching_service import MatchingService
from app.news.services.materialization.incident_materialization_service import (
    IncidentMaterializationService,
)


def repair(raw_id: int, *, apply: bool) -> None:
    with SessionLocal() as db:
        raw = db.get(RawMessage, raw_id)
        if raw is None:
            raise SystemExit(f"raw_message {raw_id} not found")
        if raw.extraction_result is None:
            raise SystemExit(f"raw_message {raw_id} has no extraction_result")

        recovered = recover_sectioned_sub_events(raw.raw_text or "")
        if len(recovered) < 2:
            raise SystemExit("refusing repair: message is not a recognized sectioned bulletin")

        alternatives: list[str] = []
        ambiguity_evidence: str | None = None
        normalized_events = []
        for event in recovered:
            _, locations, event_alternatives, evidence = (
                OllamaExtractionService._collapse_fuzzy_area_locations(
                    event.evidence_span or "",
                    [entry.village for entry in event.locations],
                    event.locations,
                )
            )
            normalized_events.append(event.model_copy(update={"locations": locations}))
            for item in event_alternatives:
                if item not in alternatives:
                    alternatives.append(item)
            ambiguity_evidence = ambiguity_evidence or evidence

        roles = []
        villages = []
        seen = set()
        for event in normalized_events:
            for entry in event.locations:
                if entry.role != VillageRole.target or entry.village in seen:
                    continue
                seen.add(entry.village)
                villages.append(entry.village)
                roles.append(entry)

        extraction = ExtractionResult.model_validate(raw.extraction_result).model_copy(
            update={
                "village": villages,
                "village_roles": roles,
                "sub_events": normalized_events,
                "location_ambiguity": bool(alternatives),
                "location_alternatives": alternatives,
                "location_ambiguity_evidence": ambiguity_evidence,
            }
        )
        matcher = MatchingService(VillageRepository(db), ConditionRepository(db))
        matched = matcher.match(
            extraction,
            cnrs_classification=raw.cnrs_classification,
        )
        preview = [
            (
                item.raw_village_text,
                item.matched_village_id,
                item.matched_condition_id,
                item.event_index,
            )
            for item in matched.village_matches
        ]
        print(f"raw={raw_id} recovered_events={len(normalized_events)} matches={preview}")
        if not apply:
            print("dry run; pass --apply to write")
            return

        active = list(
            db.scalars(
                select(Incident).where(
                    Incident.raw_message_id == raw_id,
                    Incident.is_deleted.is_(False),
                )
            ).all()
        )
        for incident in active:
            soft_delete_incident(db, incident, reason="SCRIPT_SECTIONED_REPROCESS")
        db.execute(
            delete(IncidentUpdate).where(
                IncidentUpdate.new_values["merged_from"]["raw_message_id"].astext
                == str(raw_id)
            )
        )
        raw.extraction_result = extraction.model_dump(mode="json")
        raw.match_result = matched.model_dump(mode="json")
        raw.duplicate_of_id = None
        raw.error_message = None
        db.add(raw)
        db.commit()

        incident_repo = IncidentRepository(db)
        service = IncidentMaterializationService(
            db,
            dedup_service=DedupMatchingService(incident_repository=incident_repo),
        )
        created = service.materialize(raw)
        db.commit()
        print(
            f"applied raw={raw_id} soft_deleted={len(active)} "
            f"materialized={len(created)} stats={service.stats}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("raw_id", type=int)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    repair(args.raw_id, apply=args.apply)


if __name__ == "__main__":
    main()
