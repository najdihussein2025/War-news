from datetime import datetime, timezone

from app.dtos.news import RelevanceClassificationResult
from app.interfaces.news import KeywordPrefilterInterface, RelevanceClassifierInterface
from app.models.news import MessageStatus


def classify_message(
    raw_text: str | None,
    classifier: RelevanceClassifierInterface,
    keyword_prefilter: KeywordPrefilterInterface,
) -> RelevanceClassificationResult:
    if raw_text is None or not raw_text.strip():
        return RelevanceClassificationResult(
            relevant=False,
            confidence=1.0,
            reasoning="no text content",
            model="n/a",
            classified_at=datetime.now(timezone.utc),
        )

    if not keyword_prefilter.has_candidate_keywords(raw_text):
        return RelevanceClassificationResult(
            relevant=False,
            confidence=1.0,
            reasoning="no keyword match (village/action)",
            model="keyword_prefilter",
            classified_at=datetime.now(timezone.utc),
        )

    return classifier.classify(raw_text)


def status_for_result(result: RelevanceClassificationResult) -> MessageStatus:
    if result.relevant:
        return MessageStatus.parsed
    return MessageStatus.rejected
