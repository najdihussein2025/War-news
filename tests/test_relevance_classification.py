from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx

from app.core.ollama_client import OllamaChatClient
from app.dtos.news import RelevanceClassificationResult, RelevanceConfidence
from app.models.news import MessageStatus
from app.services.news.ollama_relevance_classifier_service import (
    OllamaRelevanceClassifierService,
)
from app.services.news.relevance_filter_service import policy_for_result


def _classifier_for_model_content(content: str) -> OllamaRelevanceClassifierService:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        return httpx.Response(
            status_code=200,
            json={"message": {"content": content}},
        )

    return OllamaRelevanceClassifierService(
        OllamaChatClient(
            base_url="http://ollama.test",
            api_key=None,
            model="qwen2.5:7b",
            timeout_seconds=1,
            transport=httpx.MockTransport(handler),
        )
    )


def test_classifies_valid_relevance_json_without_live_network() -> None:
    classifier = _classifier_for_model_content(
        json.dumps(
            {
                "is_relevant": True,
                "confidence": "high",
                "reason": "Physical airstrike in Lebanon.",
            }
        )
    )

    result = classifier.classify("غارة إسرائيلية على أطراف بلدة عيتا الشعب.")

    assert result.is_relevant is True
    assert result.confidence == RelevanceConfidence.high
    assert result.reason == "Physical airstrike in Lebanon."
    assert result.model == "qwen2.5:7b"
    assert result.parse_error is None


def test_malformed_relevance_json_becomes_explicit_uncertain_result() -> None:
    classifier = _classifier_for_model_content("not json")

    result = classifier.classify("غارة على بلدة حدودية.")

    assert result.is_relevant is None
    assert result.confidence is None
    assert result.parse_error is not None


def test_extra_fields_become_explicit_uncertain_result() -> None:
    classifier = _classifier_for_model_content(
        json.dumps(
            {
                "is_relevant": False,
                "confidence": "high",
                "reason": "Political statement only.",
                "extra": "not allowed",
            }
        )
    )

    result = classifier.classify("تصريح سياسي بلا حادث ميداني.")

    assert result.is_relevant is None
    assert result.confidence is None
    assert result.parse_error is not None


def test_policy_rejects_only_high_confidence_irrelevant() -> None:
    result = RelevanceClassificationResult(
        is_relevant=False,
        confidence=RelevanceConfidence.high,
        reason="Event outside Lebanon.",
        model="test",
        classified_at=datetime.now(timezone.utc),
    )

    policy = policy_for_result(result)

    assert policy.status == MessageStatus.rejected.value
    assert policy.low_confidence_relevance is False


def test_policy_proceeds_with_warning_for_medium_confidence() -> None:
    result = RelevanceClassificationResult(
        is_relevant=True,
        confidence=RelevanceConfidence.medium,
        reason="Likely Lebanon security incident.",
        model="test",
        classified_at=datetime.now(timezone.utc),
    )

    policy = policy_for_result(result)

    assert policy.status == MessageStatus.parsed.value
    assert policy.low_confidence_relevance is True


def test_policy_proceeds_with_warning_for_parse_failure() -> None:
    result = RelevanceClassificationResult(
        is_relevant=None,
        confidence=None,
        reason="Malformed relevance classification response.",
        model="test",
        classified_at=datetime.now(timezone.utc),
        parse_error="invalid json",
    )

    policy = policy_for_result(result)

    assert policy.status == MessageStatus.parsed.value
    assert policy.low_confidence_relevance is True
