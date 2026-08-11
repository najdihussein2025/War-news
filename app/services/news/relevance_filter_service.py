from datetime import datetime, timezone

from app.dtos.news import RelevanceClassificationResult
from app.interfaces.news import RelevanceClassifierInterface
from app.models.news import MessageStatus


def classify_message(
    raw_text: str | None,
    classifier: RelevanceClassifierInterface,
) -> RelevanceClassificationResult:
    if raw_text is None or not raw_text.strip():
        return RelevanceClassificationResult(
            relevant=False,
            confidence=1.0,
            reasoning="no text content",
            model="n/a",
            classified_at=datetime.now(timezone.utc),
        )

    return classifier.classify(raw_text)


def status_for_result(result: RelevanceClassificationResult) -> str:
    if result.relevant:
        return MessageStatus.parsed.value
    return MessageStatus.rejected.value
