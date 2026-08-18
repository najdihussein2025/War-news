from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.llm.dtos import ExtractionCategory, ExtractionCategoryKey, ExtractionResult
from app.llm.services.ollama_extraction_service import OllamaExtractionService
from app.news.models import Incident, IncidentDetail, RawMessage
from app.news.services.category_mapper import compute_rollups, map_categories
from app.news.services.dedup_matching_service import DedupMatchingService
from app.news.services.embedding_service import EmbeddingService
from app.news.services.incident_detail_merge import merge_incident_detail_fields

logger = logging.getLogger(__name__)


class Tier2DetailFillService:
    def __init__(
        self,
        db: Session,
        classifier: OllamaExtractionService,
        *,
        embedding_service: EmbeddingService | None = None,
        dedup_service: DedupMatchingService | None = None,
    ) -> None:
        self.db = db
        self.classifier = classifier
        self.embedding_service = embedding_service or EmbeddingService()
        self.dedup_service = dedup_service

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
        if tier2_categories is not None:
            merged_categories = dict(extraction.categories)
            merged_categories.update(tier2_categories)
            extraction = extraction.model_copy(
                update={
                    "categories": merged_categories,
                    "extraction_tier": 2,
                    "extracted_at": datetime.now(timezone.utc),
                }
            )
            raw_message.extraction_result = extraction.model_dump(mode="json")
            self.db.add(raw_message)

        mapped_fields = map_categories(extraction.categories)
        total_deaths, total_injuries = compute_rollups(
            mapped_fields,
            extraction.casualties,
        )

        embedding = raw_message.content_embedding
        if embedding is None:
            embedding = self.embedding_service.generate(raw_message.raw_text or "")
            raw_message.content_embedding = embedding
            self.db.add(raw_message)

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

            merge_incident_detail_fields(detail, mapped_fields)
            incident.total_deaths = total_deaths
            incident.total_injuries = total_injuries
            incident.khabar_embedding = embedding
            incident.details_pending = False
            self._apply_dedup_backstop(
                incident,
                embedding,
                raw_message_id,
                mapped_fields,
            )
            self.db.add(incident)
            self.db.add(detail)
            updated += 1

        self.db.commit()
        logger.info(
            "tier2_detail_fill raw_message_id=%s updated_incidents=%s categories=%s",
            raw_message_id,
            updated,
            len(extraction.categories),
        )
        return updated

    def _apply_dedup_backstop(
        self,
        incident: Incident,
        embedding: list[float],
        raw_message_id: int,
        mapped_fields: dict,
    ) -> None:
        if self.dedup_service is None:
            return

        existing, score = self.dedup_service.find_best_match(
            village_id=incident.village_id,
            condition_id=incident.condition_id,
            event_date=incident.event_date,
            khabar_embedding=embedding,
        )
        if existing is None or existing.id == incident.id:
            return

        if score >= settings.dedup_high_threshold:
            self.dedup_service.merge_into_incident(
                existing=existing,
                new_candidate_data={
                    "deaths": incident.deaths,
                    "injuries": incident.injuries,
                    "total_deaths": incident.total_deaths,
                    "total_injuries": incident.total_injuries,
                    "khabar": incident.khabar,
                    "mapped_fields": mapped_fields,
                },
                raw_message_id=raw_message_id,
            )
            incident.is_deleted = True
            logger.info(
                "tier2 dedup merged incident_id=%s into incident_id=%s score=%.3f",
                incident.id,
                existing.id,
                score,
            )
            return

        if score >= settings.dedup_low_threshold:
            incident.duplicate_flag = True
            logger.info(
                "tier2 dedup flagged incident_id=%s possible_duplicate_of=%s score=%.3f",
                incident.id,
                existing.id,
                score,
            )
