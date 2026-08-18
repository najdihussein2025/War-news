from __future__ import annotations

from typing import Any

from app.llm.dtos import ClassificationResultDTO, ClassificationVerdict
from app.llm.interfaces import RelevanceClassifierInterface
from app.news.models import RawMessage

CNRS_PROVIDED_BACKEND = "cnrs_provided"


def _is_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def verdict_from_cnrs_classification(
    cnrs_classification: dict[str, Any] | None,
) -> ClassificationVerdict | None:
    """Return a relevance verdict from CNRS metadata, or None to fall back to LLM."""
    if not cnrs_classification:
        return None

    include = cnrs_classification.get("include")
    if include is True:
        return ClassificationVerdict.relevant
    if include is False:
        return ClassificationVerdict.not_relevant

    domain = cnrs_classification.get("event_domain")
    subtype = cnrs_classification.get("event_subtype")
    if _is_present(domain) and _is_present(subtype):
        return ClassificationVerdict.relevant

    return None


def classification_from_cnrs(
    message: RawMessage,
) -> ClassificationResultDTO | None:
    verdict = verdict_from_cnrs_classification(message.cnrs_classification)
    if verdict is None:
        return None

    cnrs = message.cnrs_classification or {}
    confidence = cnrs.get("confidence")
    parsed_confidence = (
        float(confidence)
        if isinstance(confidence, (int, float)) and not isinstance(confidence, bool)
        else None
    )
    reason = cnrs.get("reason")
    if isinstance(reason, str) and reason.strip():
        reasoning = reason.strip()
    else:
        reasoning = (
            "CNRS classification: "
            f"include={cnrs.get('include')!r}, "
            f"event_domain={cnrs.get('event_domain')!r}, "
            f"event_subtype={cnrs.get('event_subtype')!r}"
        )

    return ClassificationResultDTO(
        raw_message_id=message.id,
        verdict=verdict,
        confidence=parsed_confidence,
        reasoning=reasoning,
        backend=CNRS_PROVIDED_BACKEND,
        raw_response=dict(cnrs),
    )


class CnrsProvidedRelevanceClassifier(RelevanceClassifierInterface):
    """Use CNRS-provided verdicts when present; fall back to LLM for the rest."""

    def __init__(self, fallback: RelevanceClassifierInterface) -> None:
        self.fallback = fallback

    async def classify_batch(
        self,
        messages: list[RawMessage],
    ) -> list[ClassificationResultDTO]:
        if not messages:
            return []

        resolved: dict[int, ClassificationResultDTO] = {}
        fallback_messages: list[RawMessage] = []

        for message in messages:
            cnrs_result = classification_from_cnrs(message)
            if cnrs_result is not None:
                resolved[message.id] = cnrs_result
                continue
            fallback_messages.append(message)

        if fallback_messages:
            fallback_results = await self.fallback.classify_batch(fallback_messages)
            if len(fallback_results) != len(fallback_messages):
                raise RuntimeError(
                    "Fallback classifier result count does not match message count."
                )
            for message, result in zip(fallback_messages, fallback_results, strict=True):
                resolved[message.id] = result

        return [resolved[message.id] for message in messages]
