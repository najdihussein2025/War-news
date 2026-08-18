from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.llm.dtos import ClassificationVerdict
from app.llm.services.cnrs_relevance_classifier import (
    CNRS_PROVIDED_BACKEND,
    CnrsProvidedRelevanceClassifier,
    classification_from_cnrs,
    verdict_from_cnrs_classification,
)


def _message(
    message_id: int,
    *,
    cnrs_classification: dict | None = None,
    text: str = "غارة إسرائيلية على أطراف بلدة.",
):
    return SimpleNamespace(
        id=message_id,
        raw_text=text,
        cnrs_classification=cnrs_classification,
    )


class _FallbackStub:
    def __init__(self, responses: dict[int, object]) -> None:
        self.responses = responses
        self.calls: list[list[object]] = []

    async def classify_batch(self, messages):
        self.calls.append(messages)
        return [self.responses[message.id] for message in messages]


@pytest.mark.parametrize(
    ("cnrs", "expected"),
    [
        ({"include": True}, ClassificationVerdict.relevant),
        ({"include": False}, ClassificationVerdict.not_relevant),
        (
            {"event_domain": "security", "event_subtype": "airstrike"},
            ClassificationVerdict.relevant,
        ),
        ({"event_domain": "security"}, None),
        (None, None),
    ],
)
def test_verdict_from_cnrs_classification(cnrs, expected) -> None:
    assert verdict_from_cnrs_classification(cnrs) == expected


def test_classification_from_cnrs_uses_cnrs_backend() -> None:
    message = _message(
        1,
        cnrs_classification={
            "include": False,
            "reason": "Political statement only.",
        },
    )

    result = classification_from_cnrs(message)

    assert result is not None
    assert result.verdict == ClassificationVerdict.not_relevant
    assert result.backend == CNRS_PROVIDED_BACKEND
    assert result.reasoning == "Political statement only."


@pytest.mark.asyncio
async def test_composite_classifier_skips_llm_when_cnrs_verdict_present() -> None:
    from app.llm.dtos import ClassificationResultDTO

    fallback = _FallbackStub(
        {
            2: ClassificationResultDTO(
                raw_message_id=2,
                verdict=ClassificationVerdict.relevant,
                confidence=0.5,
                reasoning="LLM fallback",
                backend="local_llm",
            )
        }
    )
    classifier = CnrsProvidedRelevanceClassifier(fallback=fallback)  # type: ignore[arg-type]

    messages = [
        _message(1, cnrs_classification={"include": True}),
        _message(2, cnrs_classification=None),
    ]

    results = await classifier.classify_batch(messages)

    assert len(fallback.calls) == 1
    assert [message.id for message in fallback.calls[0]] == [2]
    assert results[0].backend == CNRS_PROVIDED_BACKEND
    assert results[0].verdict == ClassificationVerdict.relevant
    assert results[1].backend == "local_llm"
