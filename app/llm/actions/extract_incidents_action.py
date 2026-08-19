import logging

from app.llm.dtos import (
    ExtractPendingMessagesData,
    ExtractionBatchSummary,
)
from app.llm.interfaces import ExtractionClassifierInterface
from app.llm.services.transient_llm_errors import (
    ExtractionRetryCappedError,
    is_transient_llm_error,
)
from app.news.interfaces import RawMessageRepositoryInterface
from app.news.models import MessageStatus

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
                result = self.classifier.extract_tier1(
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
                if is_transient_llm_error(exc):
                    capped = self.raw_messages.record_transient_extraction_failure(
                        message,
                        exc,
                    )
                    if capped:
                        logger.error(
                            "Tier1 extraction capped raw_message_id=%s retry_count=%s",
                            message.id,
                            message.extraction_retry_count,
                        )
                elif message.status == MessageStatus.parsed:
                    self.raw_messages.save_error(
                        message=message,
                        error_message=str(exc),
                    )

        return ExtractionBatchSummary(
            processed=processed,
            extracted=extracted,
            errored=errored,
        )

    def execute_one(self, raw_message_id: int) -> None:
        message = self.raw_messages.get_by_id(raw_message_id)
        if message is None:
            raise LookupError(
                f"raw_message id={raw_message_id} was not found."
            )
        if message.extraction_result is not None:
            return
        if message.status != MessageStatus.parsed:
            return

        try:
            result = self.classifier.extract_tier1(
                post_text=message.raw_text or "",
                raw_message_id=message.id,
            )
            self.raw_messages.save_extraction_result(
                message=message,
                result=result,
                audited_candidates=[],
            )
        except Exception as exc:
            self.raw_messages.rollback()
            if is_transient_llm_error(exc):
                capped = self.raw_messages.record_transient_extraction_failure(
                    message,
                    exc,
                )
                if capped:
                    raise ExtractionRetryCappedError(
                        message.error_message or "extraction retry cap reached"
                    ) from exc
            elif message.status == MessageStatus.parsed:
                self.raw_messages.save_error(
                    message=message,
                    error_message=str(exc),
                )
            raise exc
