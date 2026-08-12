from datetime import datetime, timezone

from app.dtos.news import (
    RelevanceClassificationResult,
    RelevanceConfidence,
    RelevancePolicyResult,
    RelevancePolicyVerdict,
)
from app.interfaces.services import KeywordPrefilterInterface, RelevanceClassifierInterface
from app.models.news import MessageStatus


def classify_message(
    raw_text: str | None,
    classifier: RelevanceClassifierInterface,
    keyword_prefilter: KeywordPrefilterInterface,
) -> RelevanceClassificationResult:
    if raw_text is None or not raw_text.strip():
        return RelevanceClassificationResult(
            is_relevant=False,
            confidence=RelevanceConfidence.high,
            reason="no text content",
            model="n/a",
            classified_at=datetime.now(timezone.utc),
        )

    if not keyword_prefilter.has_candidate_keywords(raw_text):
        return RelevanceClassificationResult(
            is_relevant=False,
            confidence=RelevanceConfidence.high,
            reason="no keyword match (village/action)",
            model="keyword_prefilter",
            classified_at=datetime.now(timezone.utc),
        )

    return classifier.classify(raw_text)


def policy_for_result(result: RelevanceClassificationResult) -> RelevancePolicyResult:
    if (
        result.is_relevant is False
        and result.confidence == RelevanceConfidence.high
        and result.parse_error is None
    ):
        return RelevancePolicyResult(
            verdict=RelevancePolicyVerdict.reject,
            status=MessageStatus.rejected.value,
            low_confidence_relevance=False,
        )

    if (
        result.is_relevant is True
        and result.confidence == RelevanceConfidence.high
        and result.parse_error is None
    ):
        return RelevancePolicyResult(
            verdict=RelevancePolicyVerdict.proceed,
            status=MessageStatus.parsed.value,
            low_confidence_relevance=False,
        )

    return RelevancePolicyResult(
        verdict=RelevancePolicyVerdict.uncertain,
        status=MessageStatus.parsed.value,
        low_confidence_relevance=True,
    )


def status_for_result(result: RelevanceClassificationResult) -> MessageStatus:
    return MessageStatus(policy_for_result(result).status)
