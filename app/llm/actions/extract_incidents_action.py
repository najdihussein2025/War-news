import logging

from app.llm.dtos import (
    ExtractPendingMessagesData,
    ExtractionBatchSummary,
)
from app.news.interfaces import RawMessageRepositoryInterface
from app.llm.interfaces import ExtractionClassifierInterface

logger = logging.getLogger(__name__)


class ExtractIncidentsAction:
    def __init__(
        self,
        raw_messages: RawMessageRepositoryInterface,
        classifier: ExtractionClassifierInterface,
    ) -> None:
        self.raw_messages = raw_messages
        self.classifier = classifier

    def execute(self, data: ExtractPendingMessagesData) -> ExtractionBatchSummary:
        messages = self.raw_messages.get_pending_extraction_batch(
            limit=data.batch_size
        )
        processed = 0
        extracted = 0
        errored = 0

        for message in messages:
            processed += 1
            try:
                result = self.classifier.extract(
                    post_text=message.raw_text or "",
                    raw_message_id=message.id,
                )
                self.raw_messages.save_extraction_result(
                    message=message,
                    result=result,
                    audited_candidates=[],
                )
                extracted += 1
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
            extracted=extracted,
            errored=errored,
        )
