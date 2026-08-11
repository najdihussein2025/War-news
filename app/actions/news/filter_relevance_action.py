import logging

from sqlalchemy.orm import Session

from app.dtos.news import FilterBatchSummary
from app.interfaces.news import (
    RawMessageRepositoryInterface,
    RelevanceClassifierInterface,
)
from app.repositories.news import RawMessageRepository
from app.services.news import (
    GeminiRelevanceClassifier,
    classify_message,
    status_for_result,
)

logger = logging.getLogger(__name__)


def filter_pending_messages(
    db: Session,
    batch_size: int = 50,
    repository: RawMessageRepositoryInterface | None = None,
    classifier: RelevanceClassifierInterface | None = None,
) -> FilterBatchSummary:
    repository = repository or RawMessageRepository()
    classifier = classifier or GeminiRelevanceClassifier()

    processed = 0
    relevant = 0
    rejected = 0
    errored = 0

    messages = repository.get_pending_unfiltered_batch(db=db, limit=batch_size)
    for message in messages:
        processed += 1
        try:
            result = classify_message(message.raw_text, classifier)
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
        except Exception as exc:
            db.rollback()
            logger.exception("Failed to classify raw_message id=%s", message.id)
            repository.save_error(
                db=db,
                message=message,
                error_message=str(exc),
            )
            errored += 1

    return FilterBatchSummary(
        processed=processed,
        relevant=relevant,
        rejected=rejected,
        errored=errored,
    )
