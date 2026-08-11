import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.dtos.news import FilterBatchSummary, RelevanceClassificationResult
from app.interfaces.news import (
    RawMessageRepositoryInterface,
    RelevanceClassifierInterface,
)
from app.models.news import RawMessage
from app.repositories.news import RawMessageRepository
from app.services.news import GeminiRelevanceClassifier, status_for_result
from app.services.news.keyword_prefilter_service import has_candidate_keywords

logger = logging.getLogger(__name__)

GEMINI_RELEVANCE_BATCH_SIZE = 15
KEYWORD_PREFILTER_REASONING = "no keyword match (village/action)"
KEYWORD_PREFILTER_MODEL = "keyword_prefilter"


def _keyword_rejection_result() -> RelevanceClassificationResult:
    return RelevanceClassificationResult(
        relevant=False,
        confidence=1.0,
        reasoning=KEYWORD_PREFILTER_REASONING,
        model=KEYWORD_PREFILTER_MODEL,
        classified_at=datetime.now(timezone.utc),
    )


def _chunks(messages: list[RawMessage], size: int) -> list[list[RawMessage]]:
    return [
        messages[index : index + size]
        for index in range(0, len(messages), size)
    ]


def filter_pending_messages(
    db: Session,
    batch_size: int = 200,
    repository: RawMessageRepositoryInterface | None = None,
    classifier: RelevanceClassifierInterface | None = None,
) -> FilterBatchSummary:
    repository = repository or RawMessageRepository()
    classifier = classifier or GeminiRelevanceClassifier()

    messages = repository.get_pending_unfiltered_batch(db=db, limit=batch_size)
    processed = len(messages)
    relevant = 0
    rejected = 0
    errored = 0
    auto_rejected_by_keyword = 0
    gemini_calls_made = 0

    candidates: list[RawMessage] = []
    for message in messages:
        if has_candidate_keywords(message.raw_text or "", db):
            candidates.append(message)
            continue

        result = _keyword_rejection_result()
        repository.save_filter_result(
            db=db,
            message=message,
            result=result,
            new_status=status_for_result(result),
        )
        rejected += 1
        auto_rejected_by_keyword += 1

    candidate_chunks = _chunks(candidates, GEMINI_RELEVANCE_BATCH_SIZE)
    for chunk_index, chunk in enumerate(candidate_chunks):
        try:
            gemini_calls_made += 1
            results = classifier.classify_batch(
                [message.raw_text or "" for message in chunk]
            )
        except Exception as exc:
            db.rollback()
            logger.exception("Failed to classify relevance batch")
            failed_messages = [
                message
                for failed_chunk in candidate_chunks[chunk_index:]
                for message in failed_chunk
            ]
            for failed_message in failed_messages:
                repository.save_error(
                    db=db,
                    message=failed_message,
                    error_message=str(exc),
                )
            errored += len(failed_messages)
            break

        for message, result in zip(chunk, results, strict=True):
            new_status = status_for_result(result)
            repository.save_filter_result(
                db=db,
                message=message,
                result=result,
                new_status=new_status,
            )
            if result.relevant:
                relevant += 1
            else:
                rejected += 1

    return FilterBatchSummary(
        processed=processed,
        relevant=relevant,
        rejected=rejected,
        errored=errored,
        auto_rejected_by_keyword=auto_rejected_by_keyword,
        gemini_calls_made=gemini_calls_made,
    )
