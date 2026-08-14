from __future__ import annotations

import json

import httpx
import pytest

from app.core.ollama_client import OllamaChatClient
from app.llm.dtos import (
    ClassificationResultDTO,
    ClassificationVerdict,
)
from app.news.models import (
    MessageStatus,
    RawMessage,
)
from app.llm.services.local_llm_relevance_classifier import (
    LocalLLMRelevanceClassifier,
    REASON_VALIDATION_FALLBACK,
    is_valid_reason_text,
)
from app.llm.services.relevance_filter_service import policy_for_result


def _message(message_id: int, text: str = "غارة إسرائيلية على أطراف بلدة.") -> RawMessage:
    return RawMessage(
        id=message_id,
        source_id=0,
        raw_text=text,
        raw_payload={},
        status=MessageStatus.pending,
    )


def _classifier_for_model_content(content: str) -> LocalLLMRelevanceClassifier:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        return httpx.Response(
            status_code=200,
            json={"message": {"content": content}},
        )

    return LocalLLMRelevanceClassifier(
        OllamaChatClient(
            base_url="http://ollama.test",
            api_key=None,
            model="gpt-oss:20b",
            timeout_seconds=1,
            transport=httpx.MockTransport(handler),
        )
    )


@pytest.mark.asyncio
async def test_classifies_valid_relevance_batch_without_live_network() -> None:
    classifier = _classifier_for_model_content(
        json.dumps(
            {
                "results": [
                    {
                        "raw_message_id": 101,
                        "verdict": "relevant",
                        "confidence": 0.94,
                        "reasoning": "Physical airstrike in Lebanon.",
                    }
                ]
            }
        )
    )

    results = await classifier.classify_batch([_message(101)])

    assert results == [
        ClassificationResultDTO(
            raw_message_id=101,
            verdict=ClassificationVerdict.relevant,
            confidence=0.94,
            reasoning="Physical airstrike in Lebanon.",
            backend="local_llm_gpt_oss_20b",
            raw_response={
                "raw_message_id": 101,
                "verdict": "relevant",
                "confidence": 0.94,
                "reasoning": "Physical airstrike in Lebanon.",
            },
        )
    ]


@pytest.mark.asyncio
async def test_clean_arabic_reason_passes_through_unchanged() -> None:
    clean_reason = "حادث أمني واضح داخل لبنان."
    classifier = _classifier_for_model_content(
        json.dumps(
            {
                "results": [
                    {
                        "raw_message_id": 202,
                        "verdict": "relevant",
                        "confidence": 0.88,
                        "reasoning": clean_reason,
                    }
                ]
            }
        )
    )

    result = (await classifier.classify_batch([_message(202)]))[0]

    assert is_valid_reason_text(clean_reason) is True
    assert result.verdict == ClassificationVerdict.relevant
    assert result.reasoning == clean_reason


@pytest.mark.asyncio
async def test_invalid_reason_is_replaced_without_changing_verdict_or_confidence() -> None:
    classifier = _classifier_for_model_content(
        json.dumps(
            {
                "results": [
                    {
                        "raw_message_id": 303,
                        "verdict": "not_relevant",
                        "confidence": 0.91,
                        "reasoning": "该文本描述的是政治声明。",
                    }
                ]
            }
        )
    )

    result = (await classifier.classify_batch([_message(303)]))[0]

    assert result.verdict == ClassificationVerdict.not_relevant
    assert result.confidence == 0.91
    assert result.reasoning == REASON_VALIDATION_FALLBACK


@pytest.mark.asyncio
async def test_extra_field_in_one_result_does_not_fail_whole_batch() -> None:
    classifier = _classifier_for_model_content(
        json.dumps(
            {
                "results": [
                    {
                        "raw_message_id": 601,
                        "verdict": "relevant",
                        "confidence": 0.93,
                        "reasoning": "Physical airstrike in Lebanon.",
                    },
                    {
                        "raw_message_id": 602,
                        "verdict": "not_relevant",
                        "confidence": 0.82,
                        "reasonding": "该文本描述的是政治声明。",
                    },
                ]
            }
        )
    )

    results = await classifier.classify_batch([_message(601), _message(602)])

    assert [result.verdict for result in results] == [
        ClassificationVerdict.relevant,
        ClassificationVerdict.not_relevant,
    ]
    assert results[0].reasoning == "Physical airstrike in Lebanon."
    assert results[1].reasoning is None


@pytest.mark.asyncio
async def test_invalid_single_result_becomes_uncertain_without_failing_batch() -> None:
    classifier = _classifier_for_model_content(
        json.dumps(
            {
                "results": [
                    {
                        "raw_message_id": 701,
                        "verdict": "relevant",
                        "confidence": 0.93,
                        "reasoning": "Physical airstrike in Lebanon.",
                    },
                    {
                        "raw_message_id": 702,
                        "confidence": 0.82,
                        "reasoning": "Missing verdict.",
                    },
                ]
            }
        )
    )

    results = await classifier.classify_batch([_message(701), _message(702)])

    assert results[0].verdict == ClassificationVerdict.relevant
    assert results[0].reasoning == "Physical airstrike in Lebanon."
    assert results[1].raw_message_id == 702
    assert results[1].verdict == ClassificationVerdict.uncertain
    assert results[1].reasoning == "Malformed relevance classification result."
    assert results[1].raw_response is not None
    assert "parse_error" in results[1].raw_response


@pytest.mark.asyncio
async def test_malformed_relevance_json_becomes_uncertain_result() -> None:
    classifier = _classifier_for_model_content("not json")

    result = (await classifier.classify_batch([_message(404)]))[0]

    assert result.raw_message_id == 404
    assert result.verdict == ClassificationVerdict.uncertain
    assert result.confidence is None
    assert result.raw_response is not None
    assert "parse_error" in result.raw_response


@pytest.mark.asyncio
async def test_missing_message_result_becomes_uncertain_result() -> None:
    classifier = _classifier_for_model_content(json.dumps({"results": []}))

    result = (await classifier.classify_batch([_message(505)]))[0]

    assert result.raw_message_id == 505
    assert result.verdict == ClassificationVerdict.uncertain
    assert result.reasoning == "Model response omitted this message."


def test_policy_rejects_not_relevant_without_review() -> None:
    result = ClassificationResultDTO(
        raw_message_id=1,
        verdict=ClassificationVerdict.not_relevant,
        confidence=0.96,
        reasoning="Event outside Lebanon.",
        backend="test",
    )

    policy = policy_for_result(result)

    assert policy.status == MessageStatus.rejected.value
    assert policy.needs_review is False


def test_policy_proceeds_for_relevant() -> None:
    result = ClassificationResultDTO(
        raw_message_id=2,
        verdict=ClassificationVerdict.relevant,
        confidence=0.86,
        reasoning="Lebanon security incident.",
        backend="test",
    )

    policy = policy_for_result(result)

    assert policy.status == MessageStatus.parsed.value
    assert policy.needs_review is False


def test_policy_rejects_uncertain_but_marks_review_needed() -> None:
    result = ClassificationResultDTO(
        raw_message_id=3,
        verdict=ClassificationVerdict.uncertain,
        confidence=None,
        reasoning="Ambiguous post.",
        backend="test",
    )

    policy = policy_for_result(result)

    assert policy.status == MessageStatus.rejected.value
    assert policy.needs_review is True
