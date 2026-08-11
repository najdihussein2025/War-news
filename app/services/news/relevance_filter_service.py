from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.dtos.news import RelevanceClassificationResult
from app.interfaces.news import RelevanceClassifierInterface
from app.models.news import MessageStatus
from app.services.news.keyword_prefilter_service import has_candidate_keywords


def classify_message(
    raw_text: str | None,
    classifier: RelevanceClassifierInterface,
    db: Session,
) -> RelevanceClassificationResult:
    if raw_text is None or not raw_text.strip():
        return RelevanceClassificationResult(
            relevant=False,
            confidence=1.0,
            reasoning="no text content",
            model="n/a",
            classified_at=datetime.now(timezone.utc),
        )

    if not has_candidate_keywords(raw_text, db):
        return RelevanceClassificationResult(
            relevant=False,
            confidence=1.0,
            reasoning="no keyword match (village/action)",
            model="keyword_prefilter",
            classified_at=datetime.now(timezone.utc),
        )

    return classifier.classify(raw_text)


def status_for_result(result: RelevanceClassificationResult) -> str:
    if result.relevant:
        return MessageStatus.parsed.value
    return MessageStatus.rejected.value
