from __future__ import annotations

import logging

from app.api.factories.action_factory import build_extraction_classifier
from app.core.database import SessionLocal
from app.llm.dtos import ExtractionResult
from app.llm.services.cnrs_extraction_fallback import trusted_cnrs_action
from app.llm.services.transient_llm_errors import (
    ExtractionRetryCappedError,
    Tier2ExtractionFailedError,
    is_transient_llm_error,
)
from app.llm.services.ollama_auth_failures import coerce_ollama_auth_failure
from app.news.models import MessageStatus
from app.news.repositories.pipeline_claim_repository import PipelineClaimRepository
from app.news.repositories.raw_message_repository import RawMessageRepository
from app.news.services.matching.condition_evidence_override import apply_condition_evidence_override
from app.news.services.incident_details.casualty_gender_evidence import (
    apply_casualty_gender_backstops,
)

logger = logging.getLogger(__name__)


def _final_action_description(
    post_text: str,
    extracted_action: str | None,
    cnrs_classification: dict | None,
) -> str | None:
    text_action = apply_condition_evidence_override(post_text, extracted_action)
    if (
        extracted_action
        and extracted_action not in {"Bombs", "Unknown"}
        and text_action == "Bombs"
    ):
        return extracted_action
    if text_action:
        return text_action
    return trusted_cnrs_action(cnrs_classification, post_text)


def run_tier1_extraction_for_message(raw_message_id: int) -> None:
    """
    Tier1 extraction with no DB session held during Ollama calls.

    Avoids pool exhaustion when concurrent workers run long LLM requests.
    """
    with SessionLocal() as db:
        raw_messages = RawMessageRepository(db)
        message = raw_messages.get_by_id(raw_message_id)
        if message is None:
            raise LookupError(
                f"raw_message id={raw_message_id} was not found."
            )
        if message.extraction_result is not None:
            PipelineClaimRepository(db).release_claim(raw_message_id)
            return
        if message.status != MessageStatus.parsed:
            PipelineClaimRepository(db).release_claim(raw_message_id)
            return
        post_text = message.raw_text or ""
        cnrs_classification = message.cnrs_classification

    classifier = build_extraction_classifier()
    try:
        result = classifier.extract_tier1(
            post_text=post_text,
            raw_message_id=raw_message_id,
        )
        result = apply_casualty_gender_backstops(post_text, result)
        cnrs_action = trusted_cnrs_action(cnrs_classification, post_text)
        subtype = (
            str((cnrs_classification or {}).get("event_subtype") or "").strip().lower()
            or None
        )
        final_action = _final_action_description(
            post_text,
            result.action_description,
            cnrs_classification,
        )
        action_source = (
            "llm_text"
            if final_action and final_action != cnrs_action
            else "cnrs_subtype_fallback"
            if final_action and cnrs_action
            else result.action_source
        )
        result = result.model_copy(
            update={
                "action_description": final_action,
                "action_source": action_source,
                "source_event_subtype": subtype,
                "source_action_hint": cnrs_action,
            }
        )
    except Exception as exc:
        auth_failure = coerce_ollama_auth_failure(
            exc,
            stage="tier1_extraction",
        )
        if auth_failure is not None:
            raise auth_failure from exc
        if is_transient_llm_error(exc):
            with SessionLocal() as db:
                raw_messages = RawMessageRepository(db)
                message = raw_messages.get_by_id(raw_message_id)
                if (
                    message is not None
                    and message.status == MessageStatus.parsed
                    and message.extraction_result is None
                ):
                    capped = raw_messages.record_transient_extraction_failure(
                        message,
                        exc,
                    )
                    if capped:
                        logger.error(
                            "Tier1 extraction capped raw_message_id=%s "
                            "retry_count=%s error_message=%s",
                            raw_message_id,
                            message.extraction_retry_count,
                            message.error_message,
                        )
                        raise ExtractionRetryCappedError(
                            message.error_message or "extraction retry cap reached"
                        ) from exc
        else:
            with SessionLocal() as db:
                raw_messages = RawMessageRepository(db)
                message = raw_messages.get_by_id(raw_message_id)
                if (
                    message is not None
                    and message.status == MessageStatus.parsed
                    and message.extraction_result is None
                ):
                    raw_messages.save_error(message=message, error_message=str(exc))
        raise

    with SessionLocal() as db:
        raw_messages = RawMessageRepository(db)
        message = raw_messages.get_by_id(raw_message_id)
        if message is None:
            return
        if message.extraction_result is not None:
            return
        if message.status != MessageStatus.parsed:
            return
        raw_messages.save_extraction_result(
            message=message,
            result=result,
            audited_candidates=[],
        )


def run_tier2_detail_fill_for_message(raw_message_id: int) -> int:
    """Tier2 detail fill with no DB session held during Ollama calls."""
    from app.news.repositories.incident_repository import IncidentRepository
    from app.news.services.dedup.dedup_matching_service import DedupMatchingService
    from app.news.services.extraction.tier2_detail_fill_service import Tier2DetailFillService

    with SessionLocal() as db:
        raw_messages = RawMessageRepository(db)
        message = raw_messages.get_by_id(raw_message_id)
        if message is None:
            raise LookupError(
                f"raw_message id={raw_message_id} was not found."
            )
        if message.extraction_result is None:
            raise ValueError(
                f"raw_message id={raw_message_id} has no extraction_result"
            )
        post_text = message.raw_text or ""
        extraction_payload = dict(message.extraction_result)

    extraction = ExtractionResult.model_validate(extraction_payload)
    classifier = build_extraction_classifier()

    tier2_categories = None
    if extraction.extraction_tier < 2:
        try:
            tier2_categories = classifier.extract_tier2_details(
                post_text=post_text,
                presence_category_keys=extraction.presence_category_keys,
                root_casualties=extraction.casualties,
                raw_message_id=raw_message_id,
            )
        except Tier2ExtractionFailedError as exc:
            with SessionLocal() as db:
                Tier2DetailFillService(db, classifier).record_tier2_failure(
                    raw_message_id,
                    exc,
                )
            raise

    with SessionLocal() as db:
        incident_repo = IncidentRepository(db)
        service = Tier2DetailFillService(
            db,
            classifier,
            dedup_service=DedupMatchingService(incident_repo),
        )
        return service.apply_tier2_result_for_raw_message(
            raw_message_id,
            tier2_categories=tier2_categories,
        )
