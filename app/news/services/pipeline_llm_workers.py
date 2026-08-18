from __future__ import annotations

import logging

from app.api.factories.action_factory import build_extraction_classifier
from app.core.database import SessionLocal
from app.llm.dtos import ExtractionResult
from app.llm.services.transient_llm_errors import is_transient_llm_error
from app.news.models import MessageStatus
from app.news.repositories.raw_message_repository import RawMessageRepository

logger = logging.getLogger(__name__)


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
            return
        if message.status != MessageStatus.parsed:
            return
        post_text = message.raw_text or ""

    classifier = build_extraction_classifier()
    try:
        result = classifier.extract_tier1(
            post_text=post_text,
            raw_message_id=raw_message_id,
        )
    except Exception as exc:
        if not is_transient_llm_error(exc):
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
    from app.news.services.dedup_matching_service import DedupMatchingService
    from app.news.services.tier2_detail_fill_service import Tier2DetailFillService

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
        tier2_categories = classifier.extract_tier2_details(
            post_text=post_text,
            presence_category_keys=extraction.presence_category_keys,
            root_casualties=extraction.casualties,
            raw_message_id=raw_message_id,
        )

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
