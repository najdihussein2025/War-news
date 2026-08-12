import logging
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.dtos.news import ExtractPendingMessagesData, ExtractionBatchSummary
from app.interfaces.repositories import (
    ConditionRepositoryInterface,
    IncidentRepositoryInterface,
    RawMessageRepositoryInterface,
)
from app.interfaces.services import (
    ConditionResolutionInterface,
    DedupMatchingInterface,
    EmbeddingServiceInterface,
    ExtractionClassifierInterface,
    VillageMatchingInterface,
)
from app.services.news.dedup_matching_service import (
    DEDUP_HIGH_THRESHOLD,
    DEDUP_LOW_THRESHOLD,
)

logger = logging.getLogger(__name__)


class ExtractIncidentsAction:
    def __init__(
        self,
        raw_messages: RawMessageRepositoryInterface,
        incidents: IncidentRepositoryInterface,
        conditions: ConditionRepositoryInterface,
        classifier: ExtractionClassifierInterface,
        condition_resolver: ConditionResolutionInterface,
        village_matcher: VillageMatchingInterface,
        dedup_matcher: DedupMatchingInterface,
        embedding_service: EmbeddingServiceInterface,
    ) -> None:
        self.raw_messages = raw_messages
        self.incidents = incidents
        self.conditions = conditions
        self.classifier = classifier
        self.condition_resolver = condition_resolver
        self.village_matcher = village_matcher
        self.dedup_matcher = dedup_matcher
        self.embedding_service = embedding_service

    def execute(self, data: ExtractPendingMessagesData) -> ExtractionBatchSummary:
        processed = 0
        incidents_created = 0
        incidents_merged = 0
        incidents_flagged_duplicate = 0
        candidates_unmatched_village = 0
        candidates_invalid_action = 0
        errored = 0

        conditions = self.conditions.list_active()
        condition_pairs = [
            (condition.action_en, condition.action_ar) for condition in conditions
        ]
        messages = self.raw_messages.get_pending_extraction_batch(
            limit=data.batch_size
        )

        for message in messages:
            processed += 1
            audit_candidates: list[dict[str, Any]] = []
            khabar_embedding: list[float] | None = None
            try:
                if not message.message_datetime:
                    raise RuntimeError(
                        "raw_message.message_datetime is required for extraction."
                    )

                result = self.classifier.extract_candidates(
                    post_text=message.raw_text or "",
                    conditions=condition_pairs,
                )

                for candidate in result.candidates:
                    audit_entry = candidate.model_dump(mode="json")
                    condition = self.condition_resolver.resolve(
                        candidate.action_en,
                        conditions,
                    )
                    if condition is None:
                        candidates_invalid_action += 1
                        audit_entry["outcome"] = "invalid_action"
                        audit_candidates.append(audit_entry)
                        continue

                    village = self.village_matcher.match(candidate.location_text)
                    if village is None:
                        candidates_unmatched_village += 1
                        audit_entry["outcome"] = "unmatched_village"
                        audit_entry["condition_id"] = condition.id
                        audit_candidates.append(audit_entry)
                        continue

                    audit_entry["condition_id"] = condition.id
                    audit_entry["village_id"] = village.id
                    try:
                        if khabar_embedding is None:
                            khabar_embedding = self.embedding_service.generate(
                                message.raw_text or ""
                            )
                        matched_incident, dedup_score = (
                            self.dedup_matcher.find_best_match(
                                village_id=village.id,
                                condition_id=condition.id,
                                event_date=message.message_datetime.date(),
                                khabar_embedding=khabar_embedding,
                            )
                        )
                        audit_entry["dedup_score"] = dedup_score
                        if matched_incident is not None:
                            audit_entry["matched_incident_id"] = str(
                                matched_incident.id
                            )

                        if (
                            matched_incident is not None
                            and dedup_score >= DEDUP_HIGH_THRESHOLD
                        ):
                            with self.incidents.begin_nested():
                                self.dedup_matcher.merge_into_incident(
                                    existing=matched_incident,
                                    new_candidate_data={
                                        **candidate.model_dump(mode="json"),
                                        "khabar": message.raw_text or "",
                                    },
                                    raw_message_id=message.id,
                                )
                            incidents_merged += 1
                            audit_entry["outcome"] = "merged_duplicate"
                            audit_candidates.append(audit_entry)
                            continue

                        should_flag_duplicate = (
                            matched_incident is not None
                            and DEDUP_LOW_THRESHOLD
                            < dedup_score
                            < DEDUP_HIGH_THRESHOLD
                        )
                        with self.incidents.begin_nested():
                            incident = self.incidents.create_with_detail(
                                message=message,
                                candidate=candidate,
                                village_id=village.id,
                                condition_id=condition.id,
                                khabar_embedding=khabar_embedding,
                                duplicate_flag=should_flag_duplicate,
                            )
                            if should_flag_duplicate and matched_incident is not None:
                                self.incidents.create_duplicate_match(
                                    incident=incident,
                                    matched_incident=matched_incident,
                                    similarity_score=dedup_score,
                                )
                        incidents_created += 1
                        if should_flag_duplicate:
                            incidents_flagged_duplicate += 1
                            audit_entry["outcome"] = "flagged_duplicate"
                        else:
                            audit_entry["outcome"] = "created"
                        audit_entry["incident_id"] = str(incident.id)
                    except IntegrityError as exc:
                        logger.info(
                            "Skipped duplicate incident for raw_message id=%s: %s",
                            message.id,
                            exc,
                        )
                        audit_entry["outcome"] = "duplicate_exact_hash"
                    except Exception as exc:
                        errored += 1
                        logger.exception(
                            "Failed to create candidate incident for raw_message id=%s",
                            message.id,
                        )
                        audit_entry["outcome"] = "error"
                        audit_entry["error_message"] = str(exc)
                    audit_candidates.append(audit_entry)

                self.raw_messages.save_extraction_result(
                    message=message,
                    result=result,
                    audited_candidates=audit_candidates,
                )
            except Exception as exc:
                self.raw_messages.rollback()
                errored += 1
                logger.exception("Failed to extract raw_message id=%s", message.id)
                self.raw_messages.save_error(
                    message=message,
                    error_message=str(exc),
                )

        return ExtractionBatchSummary(
            processed=processed,
            incidents_created=incidents_created,
            incidents_merged=incidents_merged,
            incidents_flagged_duplicate=incidents_flagged_duplicate,
            candidates_unmatched_village=candidates_unmatched_village,
            candidates_invalid_action=candidates_invalid_action,
            errored=errored,
        )
