import asyncio
import logging

from app.dtos.news import (
    ClassificationResultDTO,
    ClassificationVerdict,
    FilterBatchSummary,
    FilterPendingMessagesData,
    RelevanceClassificationResult,
    RelevancePolicyVerdict,
)
from app.interfaces.repositories import (
    RawMessageRepositoryInterface,
)
from app.interfaces.services import (
    KeywordPrefilterInterface,
    RelevanceClassifierInterface,
)
from app.models.news import RawMessage
from app.services.news.relevance_filter_service import (
    policy_for_result,
    status_for_result,
)

logger = logging.getLogger(__name__)

RELEVANCE_BATCH_SIZE = 15
KEYWORD_PREFILTER_REASONING = "no keyword match (village/action)"
KEYWORD_PREFILTER_MODEL = "keyword_prefilter"


def _format_exception(exc: Exception) -> str:
    message = str(exc).strip()
    if message:
        return f"{type(exc).__name__}: {message}"
    return f"{type(exc).__name__} (no message)"


class FilterRelevanceAction:
    def __init__(
        self,
        raw_messages: RawMessageRepositoryInterface,
        classifier: RelevanceClassifierInterface,
        keyword_prefilter: KeywordPrefilterInterface,
        reviewer_classifier: RelevanceClassifierInterface | None = None,
        relevance_batch_size: int = RELEVANCE_BATCH_SIZE,
    ) -> None:
        self.raw_messages = raw_messages
        self.classifier = classifier
        self.keyword_prefilter = keyword_prefilter
        self.reviewer_classifier = reviewer_classifier
        self.relevance_batch_size = relevance_batch_size

    def execute(self, data: FilterPendingMessagesData) -> FilterBatchSummary:
        return asyncio.run(self.execute_async(data))

    async def execute_async(
        self,
        data: FilterPendingMessagesData,
    ) -> FilterBatchSummary:
        messages = self.raw_messages.get_pending_unfiltered_batch(
            limit=data.batch_size
        )
        processed = len(messages)
        relevant = 0
        rejected = 0
        uncertain = 0
        errored = 0
        auto_rejected_by_keyword = 0
        classifier_calls_made = 0

        candidates: list[RawMessage] = []
        for message in messages:
            if self.keyword_prefilter.has_candidate_keywords(message.raw_text or ""):
                candidates.append(message)
                continue

            result = self._keyword_rejection_result(message.id)
            policy = policy_for_result(result)
            self.raw_messages.save_filter_result(
                message=message,
                result=result,
                new_status=status_for_result(result),
                needs_review=policy.needs_review,
            )
            rejected += 1
            auto_rejected_by_keyword += 1

        candidate_chunks = self._chunks(candidates, self.relevance_batch_size)
        for chunk_index, chunk in enumerate(candidate_chunks):
            try:
                classifier_calls_made += 1
                results = await self.classifier.classify_batch(chunk)
                if len(results) != len(chunk):
                    raise RuntimeError(
                        "Classifier result count does not match message count."
                    )
            # One chunk's failure must not mark subsequent unattempted chunks as
            # errored — they haven't been tried yet.
            except Exception as exc:
                self.raw_messages.rollback()
                logger.exception(
                    "Failed to classify relevance batch "
                    "(chunk_index=%s, chunk_size=%s)",
                    chunk_index,
                    len(chunk),
                )
                try:
                    classifier_calls_made += 1
                    results = await self.classifier.classify_batch(chunk)
                    if len(results) != len(chunk):
                        raise RuntimeError(
                            "Classifier result count does not match message count."
                        )
                except Exception as retry_exc:
                    self.raw_messages.rollback()
                    logger.exception(
                        "Failed to classify relevance batch on retry "
                        "(chunk_index=%s, chunk_size=%s)",
                        chunk_index,
                        len(chunk),
                    )
                    error_message = _format_exception(retry_exc)
                    failed_messages = chunk
                    for failed_message in failed_messages:
                        self.raw_messages.save_error(
                            message=failed_message,
                            error_message=error_message,
                        )
                    errored += len(failed_messages)
                    continue

            for message, result in zip(chunk, results, strict=True):
                policy = policy_for_result(result)
                # Future reviewer classifiers can be invoked here for uncertain
                # primary results; the optional dependency is intentionally idle now.
                if (
                    self.reviewer_classifier is not None
                    and policy.verdict == RelevancePolicyVerdict.uncertain
                ):
                    pass
                new_status = status_for_result(result)
                self.raw_messages.save_filter_result(
                    message=message,
                    result=result,
                    new_status=new_status,
                    needs_review=policy.needs_review,
                )
                if policy.verdict == RelevancePolicyVerdict.proceed:
                    relevant += 1
                elif policy.verdict == RelevancePolicyVerdict.reject:
                    rejected += 1
                else:
                    uncertain += 1

        return FilterBatchSummary(
            processed=processed,
            relevant=relevant,
            rejected=rejected,
            uncertain=uncertain,
            errored=errored,
            auto_rejected_by_keyword=auto_rejected_by_keyword,
            classifier_calls_made=classifier_calls_made,
        )

    @staticmethod
    def _keyword_rejection_result(raw_message_id: int) -> RelevanceClassificationResult:
        return ClassificationResultDTO(
            raw_message_id=raw_message_id,
            verdict=ClassificationVerdict.not_relevant,
            confidence=1.0,
            reasoning=KEYWORD_PREFILTER_REASONING,
            backend=KEYWORD_PREFILTER_MODEL,
        )

    @staticmethod
    def _chunks(messages: list[RawMessage], size: int) -> list[list[RawMessage]]:
        return [
            messages[index : index + size]
            for index in range(0, len(messages), size)
        ]
