import logging
from datetime import datetime, timezone

from app.dtos.news import (
    FilterBatchSummary,
    FilterPendingMessagesData,
    RelevanceConfidence,
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


class FilterRelevanceAction:
    def __init__(
        self,
        raw_messages: RawMessageRepositoryInterface,
        classifier: RelevanceClassifierInterface,
        keyword_prefilter: KeywordPrefilterInterface,
    ) -> None:
        self.raw_messages = raw_messages
        self.classifier = classifier
        self.keyword_prefilter = keyword_prefilter

    def execute(self, data: FilterPendingMessagesData) -> FilterBatchSummary:
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

            result = self._keyword_rejection_result()
            policy = policy_for_result(result)
            self.raw_messages.save_filter_result(
                message=message,
                result=result,
                new_status=status_for_result(result),
                low_confidence_relevance=policy.low_confidence_relevance,
            )
            rejected += 1
            auto_rejected_by_keyword += 1

        candidate_chunks = self._chunks(candidates, RELEVANCE_BATCH_SIZE)
        for chunk_index, chunk in enumerate(candidate_chunks):
            try:
                classifier_calls_made += 1
                results = self.classifier.classify_batch(
                    [message.raw_text or "" for message in chunk]
                )
            except Exception as exc:
                self.raw_messages.rollback()
                logger.exception("Failed to classify relevance batch")
                failed_messages = [
                    message
                    for failed_chunk in candidate_chunks[chunk_index:]
                    for message in failed_chunk
                ]
                for failed_message in failed_messages:
                    self.raw_messages.save_error(
                        message=failed_message,
                        error_message=str(exc),
                    )
                errored += len(failed_messages)
                break

            for message, result in zip(chunk, results, strict=True):
                policy = policy_for_result(result)
                new_status = status_for_result(result)
                self.raw_messages.save_filter_result(
                    message=message,
                    result=result,
                    new_status=new_status,
                    low_confidence_relevance=policy.low_confidence_relevance,
                )
                # Step B plugs into raw_messages with status=parsed. When this
                # flag is true, extraction may continue but the UI can warn.
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
    def _keyword_rejection_result() -> RelevanceClassificationResult:
        return RelevanceClassificationResult(
            is_relevant=False,
            confidence=RelevanceConfidence.high,
            reason=KEYWORD_PREFILTER_REASONING,
            model=KEYWORD_PREFILTER_MODEL,
            classified_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _chunks(messages: list[RawMessage], size: int) -> list[list[RawMessage]]:
        return [
            messages[index : index + size]
            for index in range(0, len(messages), size)
        ]
