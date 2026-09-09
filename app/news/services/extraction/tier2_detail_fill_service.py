from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.llm.dtos import CasualtyScope, ExtractionCategory, ExtractionCategoryKey, ExtractionResult
from app.llm.services.ollama_extraction_service import OllamaExtractionService
from app.news.models import (
    Incident,
    IncidentDetail,
    IncidentUpdate,
    MessageStatus,
    RawMessage,
    UpdateAction,
)
from app.news.repositories.emergency_organization_repository import (
    EmergencyOrganizationRepository,
)
from app.news.repositories.bulletin_casualty_group_repository import (
    BulletinCasualtyGroupRepository,
)
from app.news.models.bulletin_casualty_group import CasualtyScope as StoredCasualtyScope
from app.news.services.incident_details.category_mapper import (
    compute_rollups,
    map_categories,
    suppress_category_casualties,
)
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
        bulletin_groups: BulletinCasualtyGroupRepository | None = None,
    ) -> None:
        self.db = db
        self.classifier = classifier
        self.embedding_service = embedding_service or EmbeddingService()
        self.dedup_service = dedup_service
        self.bulletin_groups = bulletin_groups or BulletinCasualtyGroupRepository(db)
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
        target_village_ids = self._target_village_ids(raw_message.match_result)
        is_multi_village = len(target_village_ids) > 1
        category_casualties_suppressed = False
        if is_multi_village:
            mapped_fields, category_casualties_suppressed = (
                suppress_category_casualties(mapped_fields)
            )
            category_casualties_suppressed = (
                category_casualties_suppressed
                or self._has_root_demographic_casualties(extraction)
            )
        total_deaths, total_injuries = compute_rollups(
            mapped_fields,
            extraction.casualties,
        )
        is_multi_village_aggregate = (
            extraction.casualty_scope == CasualtyScope.bulletin_aggregate
            and is_multi_village
        )
        if is_multi_village_aggregate:
            self.bulletin_groups.create_for_message(
                raw_message_id=raw_message_id,
                village_ids=target_village_ids,
                casualty_scope=StoredCasualtyScope.bulletin_aggregate,
                total_deaths=extraction.casualties.total_deaths,
                total_injuries=extraction.casualties.total_injuries,
                created_at=raw_message.message_datetime,
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
            root_demographics = {
                "male_d": root.male_deaths,
                "male_i": root.male_injuries,
                "female_d": root.female_deaths,
                "female_i": root.female_injuries,
                "children_d": root.children_deaths,
                "children_i": root.children_injuries,
            }
            if is_multi_village:
                root_demographics = {
                    field: None for field in root_demographics
                }
            merge_incident_detail_fields(
                detail,
                {
                    **mapped_fields,
                    **root_demographics,
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
            if (
                not is_multi_village_aggregate
                and incident.deaths in (None, 0)
                and root.deaths is not None
            ):
                incident.deaths = root.deaths
            if (
                not is_multi_village_aggregate
                and incident.injuries in (None, 0)
                and root.injuries is not None
            ):
                incident.injuries = root.injuries
            if (
                not is_multi_village_aggregate
                and incident.total_deaths in (None, 0)
                and total_deaths is not None
            ):
                incident.total_deaths = total_deaths
            if (
                not is_multi_village_aggregate
                and incident.total_injuries in (None, 0)
                and total_injuries is not None
            ):
                incident.total_injuries = total_injuries
            self._fill_missing_matches(
                incident,
                getattr(raw_message, "match_result", None),
            )
            incident.khabar_embedding = embedding
            incident.details_pending = False
            if category_casualties_suppressed:
                incident.verification_status = "needs_verification"
                incident.verification_reason = (
                    "Category casualties require manual per-village confirmation "
                    "for a multi-target bulletin"
                )
            if extraction.casualty_scope_needs_review:
                incident.verification_status = "needs_verification"
                incident.verification_reason = extraction.casualty_scope_review_reason
                self._record_scope_downgrade(
                    incident,
                    raw_message_id=raw_message_id,
                    reason=extraction.casualty_scope_review_reason,
                )
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
    def _target_village_ids(match_result: dict | None) -> list[int]:
        if not match_result:
            return []
        matches = match_result.get("village_matches")
        if not isinstance(matches, list):
            village_id = match_result.get("matched_village_id")
            return [village_id] if isinstance(village_id, int) else []
        return sorted(
            {
                village_id
                for item in matches
                if isinstance(item, dict)
                and item.get("village_role", "target") == "target"
                and isinstance((village_id := item.get("matched_village_id")), int)
                and not isinstance(village_id, bool)
            }
        )

    @staticmethod
    def _has_root_demographic_casualties(extraction: ExtractionResult) -> bool:
        root = extraction.casualties
        return any(
            value is not None
            for value in (
                root.male_deaths,
                root.male_injuries,
                root.female_deaths,
                root.female_injuries,
                root.children_deaths,
                root.children_injuries,
            )
        )

    def _record_scope_downgrade(
        self,
        incident: Incident,
        *,
        raw_message_id: int,
        reason: str | None,
    ) -> None:
        if not reason:
            return
        already_recorded = self.db.scalar(
            select(IncidentUpdate.id).where(
                IncidentUpdate.incident_id == incident.id,
                IncidentUpdate.action == UpdateAction.pipeline_merge,
                IncidentUpdate.new_values[
                    "casualty_scope_source_raw_message_id"
                ].astext
                == str(raw_message_id),
            )
        )
        if already_recorded is not None:
            return
        self.db.add(
            IncidentUpdate(
                incident_id=incident.id,
                action=UpdateAction.pipeline_merge,
                old_values={"casualty_scope": "unsupported_model_claim"},
                new_values={
                    "casualty_scope": CasualtyScope.unspecified.value,
                    "casualty_scope_source_raw_message_id": raw_message_id,
                    "downgrade_reason": reason,
                },
                performed_by=None,
            )
        )

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
            incident.verification_status = "needs_verification"
            incident.verification_reason = "Possible duplicate detected during detail extraction"
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
