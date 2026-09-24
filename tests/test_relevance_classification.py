from __future__ import annotations

import json

import httpx
import pytest

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401

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
from app.llm.services.relevance_guardrails import (
    apply_relevance_guardrails,
    relevance_guardrail_result,
)


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


def test_guardrail_rejects_ordinary_property_fire_without_war_context() -> None:
    result = relevance_guardrail_result(
        raw_message_id=10,
        text="اندلاع حريق داخل منزل في النبطية بسبب ماس كهربائي",
    )

    assert result is not None
    assert result.verdict == ClassificationVerdict.not_relevant
    assert "ordinary fire" in (result.reasoning or "").lower()


def test_guardrail_rejects_abbassiyet_car_fire_without_war_context() -> None:
    result = relevance_guardrail_result(
        raw_message_id=16,
        text="\u0627\u0644\u0646\u064a\u0631\u0627\u0646 \u062a\u0644\u062a\u0647\u0645 \u0633\u064a\u0627\u0631\u0629 \u0641\u064a \u0627\u0644\u0639\u0628\u0627\u0633\u064a\u0629... \u062d\u0631\u064a\u0642 \u0643\u0628\u064a\u0631 \u0634\u0631\u0642 \u0635\u0648\u0631",
    )

    assert result is not None
    assert result.verdict == ClassificationVerdict.not_relevant
    assert "ordinary fire" in (result.reasoning or "").lower()


@pytest.mark.parametrize(
    "text",
    [
        "قطع طريق بسبب حادث سير وزحمة خانقة في صور",
        "حفر وجرف ضمن أشغال بلدية لتأهيل الطريق",
        "قطع أشجار ضمن أعمال تنظيف زراعية",
        "إطلاق نار خلال إشكال فردي في أحد الأحياء",
        "العثور على جسم مشبوه غير منفجر قرب مكب نفايات",
        "انفجار اسطوانة غاز داخل محل في النبطية",
        "Traffic accident caused road closure near Tyre",
        "Shooting during a personal dispute in Nabatieh",
    ],
)
def test_guardrail_rejects_effect_only_incidents_without_war_context(text: str) -> None:
    result = relevance_guardrail_result(raw_message_id=17, text=text)

    assert result is not None
    assert result.verdict == ClassificationVerdict.not_relevant
    assert "effect-only" in (result.reasoning or "").lower()


@pytest.mark.parametrize(
    "text",
    [
        "قطع طريق بعد قصف مدفعي إسرائيلي استهدف الطريق العام",
        "حفر وجرف نفذته جرافات العدو الإسرائيلي قرب الحدود",
        "قطع أشجار نفذته قوات العدو خلال توغل بري",
        "إطلاق نار معاد من موقع للعدو الإسرائيلي باتجاه البلدة",
        "العثور على قذائف لم تنفجر من مخلفات قصف إسرائيلي",
        "انفجار عبوة ناسفة زرعتها قوات العدو خلال توغل بري",
    ],
)
def test_guardrail_keeps_effect_only_incidents_with_war_context(text: str) -> None:
    assert relevance_guardrail_result(raw_message_id=18, text=text) is None


def test_guardrail_keeps_fire_with_israeli_war_context_for_classifier() -> None:
    result = relevance_guardrail_result(
        raw_message_id=11,
        text="اندلاع حريق في منزل في النبطية جراء قصف إسرائيلي",
    )

    assert result is None


def test_guardrail_rejects_palestine_only_locations() -> None:
    result = relevance_guardrail_result(
        raw_message_id=12,
        text="إصابات جراء قصف في رام الله وغزة",
    )

    assert result is not None
    assert result.verdict == ClassificationVerdict.not_relevant
    assert "palestine" in (result.reasoning or "").lower()


def test_guardrail_rejects_janine_transliteration() -> None:
    result = relevance_guardrail_result(
        raw_message_id=14,
        text="Bombs reported in Janine after military orders.",
    )

    assert result is not None
    assert result.verdict == ClassificationVerdict.not_relevant
    assert "palestine" in (result.reasoning or "").lower()


@pytest.mark.parametrize(
    "location",
    [
        "Jerusalem",
        "Bethlehem",
        "Hebron",
        "Tulkarm",
        "Qalqilya",
        "Beit Lahia",
        "Jabalia",
        "Deir al Balah",
        "Nuseirat",
        "Khan Yunis",
    ],
)
def test_guardrail_rejects_common_palestine_locations(location: str) -> None:
    result = relevance_guardrail_result(
        raw_message_id=15,
        text=f"Bombardment reported in {location}.",
    )

    assert result is not None
    assert result.verdict == ClassificationVerdict.not_relevant
    assert "palestine" in (result.reasoning or "").lower()


def test_guardrail_overrides_false_positive_model_result() -> None:
    model_result = ClassificationResultDTO(
        raw_message_id=13,
        verdict=ClassificationVerdict.relevant,
        confidence=0.9,
        reasoning="Fire in a known village.",
        backend="test",
    )

    result = apply_relevance_guardrails(
        _message(13, "حريق سيارة في النبطية بسبب عطل كهربائي"),
        model_result,
    )

    assert result.verdict == ClassificationVerdict.not_relevant
