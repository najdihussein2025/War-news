import hashlib
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.dtos.news import ExtractedCandidate, ExtractionBatchSummary
from app.interfaces.news import ExtractionClassifierInterface
from app.models.news import (
    Condition,
    DuplicateMatch,
    Incident,
    IncidentDetail,
    MatchStatus,
    MatchType,
    MessageStatus,
    RawMessage,
)
from app.services.news import (
    DEDUP_HIGH_THRESHOLD,
    DEDUP_LOW_THRESHOLD,
    GeminiExtractionClassifier,
    find_best_match,
    match_village,
    merge_into_incident,
    resolve_condition,
)

logger = logging.getLogger(__name__)


def extract_pending_messages(
    db: Session,
    batch_size: int = 50,
    classifier: ExtractionClassifierInterface | None = None,
) -> ExtractionBatchSummary:
    classifier = classifier or GeminiExtractionClassifier()

    processed = 0
    incidents_created = 0
    incidents_merged = 0
    incidents_flagged_duplicate = 0
    candidates_unmatched_village = 0
    candidates_invalid_action = 0
    errored = 0

    conditions = _list_active_conditions(db)
    condition_pairs = [(condition.action_en, condition.action_ar) for condition in conditions]
    messages = _get_pending_extraction_batch(db=db, limit=batch_size)

    for message in messages:
        processed += 1
        audit_candidates: list[dict[str, Any]] = []
        khabar_embedding: list[float] | None = None
        try:
            if not message.message_datetime:
                raise RuntimeError("raw_message.message_datetime is required for extraction.")

            result = classifier.extract_candidates(
                post_text=message.raw_text or "",
                conditions=condition_pairs,
            )

            for candidate in result.candidates:
                audit_entry = candidate.model_dump(mode="json")
                condition = resolve_condition(candidate.action_en, conditions)
                if condition is None:
                    candidates_invalid_action += 1
                    audit_entry["outcome"] = "invalid_action"
                    audit_candidates.append(audit_entry)
                    continue

                village = match_village(candidate.location_text, db)
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
                        khabar_embedding = _generate_khabar_embedding(
                            message.raw_text or ""
                        )
                    matched_incident, dedup_score = find_best_match(
                        db=db,
                        village_id=village.id,
                        condition_id=condition.id,
                        event_date=message.message_datetime.date(),
                        khabar_embedding=khabar_embedding,
                    )
                    audit_entry["dedup_score"] = dedup_score
                    if matched_incident is not None:
                        audit_entry["matched_incident_id"] = str(matched_incident.id)

                    if matched_incident is not None and dedup_score >= DEDUP_HIGH_THRESHOLD:
                        with db.begin_nested():
                            merge_into_incident(
                                db=db,
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
                        and DEDUP_LOW_THRESHOLD < dedup_score < DEDUP_HIGH_THRESHOLD
                    )
                    with db.begin_nested():
                        incident = _create_incident_with_detail(
                            db=db,
                            message=message,
                            candidate=candidate,
                            village_id=village.id,
                            condition_id=condition.id,
                            khabar_embedding=khabar_embedding,
                            duplicate_flag=should_flag_duplicate,
                        )
                        if should_flag_duplicate:
                            _create_duplicate_match(
                                db=db,
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

            message.extraction_result = {
                **result.model_dump(mode="json"),
                "candidates": audit_candidates,
            }
            message.error_message = None
            db.add(message)
            db.commit()
        except Exception as exc:
            db.rollback()
            errored += 1
            logger.exception("Failed to extract raw_message id=%s", message.id)
            message.status = MessageStatus.error
            message.error_message = str(exc)
            db.add(message)
            db.commit()

    return ExtractionBatchSummary(
        processed=processed,
        incidents_created=incidents_created,
        incidents_merged=incidents_merged,
        incidents_flagged_duplicate=incidents_flagged_duplicate,
        candidates_unmatched_village=candidates_unmatched_village,
        candidates_invalid_action=candidates_invalid_action,
        errored=errored,
    )


def _get_pending_extraction_batch(db: Session, limit: int) -> list[RawMessage]:
    return list(
        db.scalars(
            select(RawMessage)
            .where(
                RawMessage.status == MessageStatus.parsed,
                RawMessage.extraction_result.is_(None),
            )
            .order_by(RawMessage.id.asc())
            .limit(limit)
        ).all()
    )


def _list_active_conditions(db: Session) -> list[Condition]:
    return list(
        db.scalars(
            select(Condition)
            .where(Condition.is_active.is_(True))
            .order_by(Condition.id.asc())
        ).all()
    )


def _create_incident_with_detail(
    db: Session,
    message: RawMessage,
    candidate: ExtractedCandidate,
    village_id: int,
    condition_id: int,
    khabar_embedding: list[float],
    duplicate_flag: bool = False,
) -> Incident:
    event_datetime = message.message_datetime
    if event_datetime is None:
        raise RuntimeError("raw_message.message_datetime is required for incident creation.")

    exact_hash = _build_exact_hash(
        khabar=message.raw_text or "",
        village_id=village_id,
        condition_id=condition_id,
        event_date=event_datetime.date().isoformat(),
    )

    incident = Incident(
        village_id=village_id,
        condition_id=condition_id,
        source_id=message.source_id,
        raw_message_id=message.id,
        event_date=event_datetime.date(),
        event_time=event_datetime.time(),
        khabar=message.raw_text or "",
        khabar_embedding=khabar_embedding,
        deaths=candidate.deaths,
        injuries=candidate.injuries,
        exact_hash=exact_hash,
        duplicate_flag=duplicate_flag,
        created_by=None,
    )
    db.add(incident)
    db.flush()
    detail = IncidentDetail(
        incident_id=incident.id,
        male_d=candidate.male_d,
        male_i=candidate.male_i,
        female_d=candidate.female_d,
        female_i=candidate.female_i,
        children_d=candidate.children_d,
        children_i=candidate.children_i,
    )
    db.add(detail)
    db.flush()
    return incident


def _create_duplicate_match(
    db: Session,
    incident: Incident,
    matched_incident: Incident,
    similarity_score: float,
) -> None:
    duplicate_match = DuplicateMatch(
        incident_id=incident.id,
        matched_incident_id=matched_incident.id,
        match_type=MatchType.soft,
        similarity_score=similarity_score,
        status=MatchStatus.pending,
    )
    db.add(duplicate_match)
    db.flush()


def _build_exact_hash(
    khabar: str,
    village_id: int,
    condition_id: int,
    event_date: str,
) -> str:
    normalized = " ".join(khabar.split())
    key = f"{normalized}|{village_id}|{condition_id}|{event_date}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _generate_khabar_embedding(text: str) -> list[float]:
    from app.services.news.embedding_service import generate_embedding

    return generate_embedding(text)
