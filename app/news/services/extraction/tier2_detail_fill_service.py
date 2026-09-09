from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.llm.dtos import ExtractionCategory, ExtractionCategoryKey, ExtractionResult
from app.llm.services.ollama_extraction_service import OllamaExtractionService
from app.news.models import Incident, IncidentDetail, MessageStatus, RawMessage
from app.news.repositories.emergency_organization_repository import (
    EmergencyOrganizationRepository,
)
from app.news.services.incident_details.category_mapper import compute_rollups, map_categories
from app.news.services.incident_details.casualty_demographic_consistency import reconcile_root_demographics
from app.news.services.dedup.dedup_matching_service import DedupMatchingService
from app.news.services.clustering.embedding_service import EmbeddingService
from app.news.services.matching.emergency_organization_matching_service import (
    EmergencyOrganizationMatchingService,
)
from app.news.services.incident_details.incident_detail_merge import merge_incident_detail_fields

logger = logging.getLogger(__name__)


class Tier2DetailFillService:
    def __init__(
        self,
        db: Session,
        classifier: OllamaExtractionService,
        *,
        embedding_service: EmbeddingService | None = None,
        dedup_service: DedupMatchingService | None = None,
        emergency_org_matcher: EmergencyOrganizationMatchingService | None = None,
    ) -> None:
        self.db = db
        self.classifier = classifier
        self.embedding_service = embedding_service or EmbeddingService()
        self.dedup_service = dedup_service
        self.emergency_org_matcher = (
            emergency_org_matcher
            or EmergencyOrganizationMatchingService(
                EmergencyOrganizationRepository(db)
            )
        )

    def fill_for_raw_message(self, raw_message_id: int) -> int:
        """Fill category details (includes LLM calls when tier2 is incomplete)."""
        raw_message = self.db.get(RawMessage, raw_message_id)
        if raw_message is None:
            raise LookupError(f"RawMessage id={raw_message_id} was not found.")
        if raw_message.extraction_result is None:
            raise ValueError(
                f"raw_message id={raw_message_id} has no extraction_result"
            )

        extraction = ExtractionResult.model_validate(raw_message.extraction_result)
        tier2_categories = None
        if extraction.extraction_tier < 2:
            tier2_categories = self.classifier.extract_tier2_details(
                post_text=raw_message.raw_text or "",
                presence_category_keys=extraction.presence_category_keys,
                root_casualties=extraction.casualties,
                raw_message_id=raw_message_id,
            )
        return self.apply_tier2_result_for_raw_message(
            raw_message_id,
            tier2_categories=tier2_categories,
        )

    def apply_tier2_result_for_raw_message(
        self,
        raw_message_id: int,
        *,
        tier2_categories: dict[ExtractionCategoryKey, ExtractionCategory] | None = None,
    ) -> int:
        """
        Persist tier2 category details for all details_pending incidents on one message.

        When ``tier2_categories`` is supplied, merges them into the stored extraction
        payload before updating incidents. Pass ``None`` when tier2 is already complete.
        """
        raw_message = self.db.get(RawMessage, raw_message_id)
        if raw_message is None:
            raise LookupError(f"RawMessage id={raw_message_id} was not found.")
        if raw_message.extraction_result is None:
            raise ValueError(
                f"raw_message id={raw_message_id} has no extraction_result"
            )

        incidents = list(
            self.db.scalars(
                select(Incident).where(
                    Incident.raw_message_id == raw_message_id,
                    Incident.details_pending.is_(True),
                    Incident.is_deleted.is_(False),
                )
            ).all()
        )
        if not incidents:
            return 0

        extraction = ExtractionResult.model_validate(raw_message.extraction_result)
        original_root_casualties = extraction.casualties
        if tier2_categories is not None:
            merged_categories = dict(extraction.categories)
            merged_categories.update(tier2_categories)
            reconciled_casualties = reconcile_root_demographics(
                extraction.casualties,
                merged_categories,
            )
            extraction = extraction.model_copy(
                update={
                    "categories": merged_categories,
                    "casualties": reconciled_casualties,
                    "extraction_tier": 2,
                    "extracted_at": datetime.now(timezone.utc),
                }
            )
            raw_message.extraction_result = extraction.model_dump(mode="json")
            self.db.add(raw_message)
        else:
            reconciled_casualties = reconcile_root_demographics(
                extraction.casualties,
                extraction.categories,
            )
            if reconciled_casualties != extraction.casualties:
                extraction = extraction.model_copy(
                    update={"casualties": reconciled_casualties}
                )
                raw_message.extraction_result = extraction.model_dump(mode="json")
                self.db.add(raw_message)

        mapped_fields = map_categories(
            extraction.categories,
            emergency_org_matcher=self.emergency_org_matcher,
        )
        total_deaths, total_injuries = compute_rollups(
            mapped_fields,
            extraction.casualties,
        )

        embedding = raw_message.content_embedding

        updated = 0
        for incident in incidents:
            detail = self.db.scalar(
                select(IncidentDetail).where(
                    IncidentDetail.incident_id == incident.id
                )
            )
            if detail is None:
                detail = IncidentDetail(incident_id=incident.id)
                self.db.add(detail)
                self.db.flush()

            root = extraction.casualties
            merge_incident_detail_fields(
                detail,
                {
                    **mapped_fields,
                    "male_d": root.male_deaths,
                    "male_i": root.male_injuries,
                    "female_d": root.female_deaths,
                    "female_i": root.female_injuries,
                    "children_d": root.children_deaths,
                    "children_i": root.children_injuries,
                },
            )
            # Reconciliation is allowed to clear a contradictory positive
            # gender value; the ordinary merge helper intentionally ignores
            # None and therefore cannot perform this correction itself.
            demographic_fields = {
                "male_deaths": "male_d",
                "male_injuries": "male_i",
                "female_deaths": "female_d",
                "female_injuries": "female_i",
            }
            for extraction_field, detail_field in demographic_fields.items():
                before = getattr(original_root_casualties, extraction_field)
                after = getattr(root, extraction_field)
                if before != after:
                    setattr(detail, detail_field, after)
            if incident.deaths in (None, 0) and root.deaths is not None:
                incident.deaths = root.deaths
            if incident.injuries in (None, 0) and root.injuries is not None:
                incident.injuries = root.injuries
            if incident.total_deaths in (None, 0) and total_deaths is not None:
                incident.total_deaths = total_deaths
            if incident.total_injuries in (None, 0) and total_injuries is not None:
                incident.total_injuries = total_injuries
            self._fill_missing_matches(
                incident,
                getattr(raw_message, "match_result", None),
            )
            incident.khabar_embedding = embedding
            incident.details_pending = False
            self._apply_dedup_backstop(
                incident,
                embedding,
                raw_message_id,
                mapped_fields,
                [
                    item.model_dump(mode="json")
                    for item in extraction.casualty_transitions
                ],
            )
            self.db.add(incident)
            self.db.add(detail)
            updated += 1

        # Tier 2 detail fill completed for this message: stamp it in the same
        # commit that flips details_pending to false above. Only reached when
        # at least one details_pending incident actually needed filling.
        raw_message.tier2_completed_at = datetime.now(timezone.utc)
        raw_message.materialized_at = datetime.now(timezone.utc)
        if getattr(raw_message, "status", None) != MessageStatus.duplicate:
            raw_message.status = MessageStatus.materialized
        raw_message.error_message = None
        self.db.add(raw_message)
        self.db.commit()
        logger.info(
            "tier2_detail_fill raw_message_id=%s updated_incidents=%s categories=%s",
            raw_message_id,
            updated,
            len(extraction.categories),
        )
        return updated

    @staticmethod
    def _fill_missing_matches(
        incident: Incident,
        match_result: dict | None,
    ) -> None:
        if not match_result:
            return
        if incident.condition_id is None:
            condition_id = match_result.get("matched_condition_id")
            if isinstance(condition_id, int):
                incident.condition_id = condition_id
        if incident.village_id is not None:
            return
        for village in match_result.get("village_matches") or []:
            if village.get("village_role", "target") != "target":
                continue
            if village.get("village_match_status") not in {
                "matched",
                "matched_low_confidence",
            }:
                continue
            village_id = village.get("matched_village_id")
            if isinstance(village_id, int):
                incident.village_id = village_id
                return

    def _apply_dedup_backstop(
        self,
        incident: Incident,
        embedding: list[float] | None,
        raw_message_id: int,
        mapped_fields: dict,
        casualty_transitions: list[dict],
    ) -> None:
        if self.dedup_service is None or embedding is None:
            return

        existing, score = self.dedup_service.find_best_match(
            village_id=incident.village_id,
            condition_id=incident.condition_id,
            event_date=incident.event_date,
            khabar_embedding=embedding,
            exclude_raw_message_id=incident.raw_message_id or raw_message_id,
            event_time=incident.event_time,
        )
        if existing is None or existing.id == incident.id:
            return

        if score >= settings.dedup_high_threshold:
            candidate_data = {
                "deaths": incident.deaths,
                "injuries": incident.injuries,
                "total_deaths": incident.total_deaths,
                "total_injuries": incident.total_injuries,
                "khabar": incident.khabar,
                "mapped_fields": mapped_fields,
                "casualty_transitions": casualty_transitions,
            }
            canonicalize = getattr(
                self.dedup_service, "canonicalize_existing_incident", None
            )
            if canonicalize is not None:
                canonicalize(
                    canonical=existing,
                    duplicate=incident,
                    new_candidate_data=candidate_data,
                    similarity_score=score,
                )
            else:
                self.dedup_service.merge_into_incident(
                    existing=existing,
                    new_candidate_data=candidate_data,
                    raw_message_id=raw_message_id,
                )
            logger.info(
                "tier2 dedup canonicalized incident_id=%s into incident_id=%s score=%.3f",
                incident.id,
                existing.id,
                score,
            )
            return

        if score >= settings.dedup_low_threshold:
            incident.duplicate_flag = True
            self.dedup_service.record_possible_duplicate(
                incident=incident,
                matched_incident=existing,
                similarity_score=score,
            )
            logger.info(
                "tier2 dedup flagged incident_id=%s possible_duplicate_of=%s score=%.3f",
                incident.id,
                existing.id,
                score,
            )
