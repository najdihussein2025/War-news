from __future__ import annotations

import json
import logging

import httpx

from app.core.ollama_client import OllamaChatClient
from app.llm.dtos import (
    DidValue,
    ExtractionCasualties,
    ExtractionCategory,
    ExtractionCategoryKey,
)
from app.llm.services.ollama_extraction_service import OllamaExtractionService
from app.llm.services.ollama_presence_gate_service import OllamaPresenceGateService


class _PresenceGateStub:
    def __init__(self, categories: list[ExtractionCategoryKey]) -> None:
        self.categories = categories
        self.calls = 0

    def categories_present(
        self,
        post_text: str,
        raw_message_id: int | None = None,
    ) -> list[ExtractionCategoryKey]:
        self.calls += 1
        return self.categories


class _CategoryDetailStub:
    def __init__(
        self,
        details: dict[ExtractionCategoryKey, ExtractionCategory],
    ) -> None:
        self.details = details
        self.calls: list[ExtractionCategoryKey] = []

    def extract_detail(
        self,
        post_text: str,
        category_key: ExtractionCategoryKey,
        raw_message_id: int | None = None,
    ) -> ExtractionCategory:
        self.calls.append(category_key)
        return self.details[category_key]


def _client_for_model_contents(contents: list[str]) -> OllamaChatClient:
    remaining_contents = contents.copy()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        return httpx.Response(
            status_code=200,
            json={"message": {"content": remaining_contents.pop(0)}},
        )

    return OllamaChatClient(
        base_url="http://ollama.test",
        api_key=None,
        model="qwen2.5:7b",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )


def _general_response() -> str:
    return json.dumps(
        {
            "is_relevant": True,
            "village": "بنت جبيل",
            "action_description": "غارة على المدينة",
            "casualties": {"injuries": 1},
        },
        ensure_ascii=False,
    )


def test_orchestration_skips_category_detail_when_presence_gate_is_empty() -> None:
    presence_gate = _PresenceGateStub(categories=[])
    category_detail = _CategoryDetailStub(details={})
    service = OllamaExtractionService(
        client=_client_for_model_contents([_general_response()]),
        presence_gate=presence_gate,
        category_detail=category_detail,
    )

    result = service.extract("sample text", raw_message_id=42)

    assert presence_gate.calls == 1
    assert category_detail.calls == []
    assert result.village == "بنت جبيل"
    assert result.categories == {}


def test_orchestration_extracts_detail_once_per_present_category() -> None:
    presence_gate = _PresenceGateStub(
        categories=[
            ExtractionCategoryKey.health_center,
            ExtractionCategoryKey.vehicles,
        ]
    )
    category_detail = _CategoryDetailStub(
        details={
            ExtractionCategoryKey.health_center: ExtractionCategory(
                did=DidValue.direct,
                name="مركز صحي",
                casualties=None,
            ),
            ExtractionCategoryKey.vehicles: ExtractionCategory(
                did=DidValue.direct,
                name="سيارة",
                casualties=ExtractionCasualties(injuries=1),
            ),
        }
    )
    service = OllamaExtractionService(
        client=_client_for_model_contents([_general_response()]),
        presence_gate=presence_gate,
        category_detail=category_detail,
    )

    result = service.extract("sample text", raw_message_id=42)

    assert category_detail.calls == [
        ExtractionCategoryKey.health_center,
        ExtractionCategoryKey.vehicles,
    ]
    assert len(result.categories) == 2
    assert (
        result.categories[ExtractionCategoryKey.health_center].name
        == "مركز صحي"
    )
    assert result.categories[ExtractionCategoryKey.vehicles].casualties == (
        ExtractionCasualties(injuries=1)
    )


def test_presence_gate_drops_invalid_category_key_and_logs(caplog) -> None:
    service = OllamaPresenceGateService(
        _client_for_model_contents(
            [
                json.dumps(
                    {
                        "categories_present": [
                            "vehicles",
                            "attack",
                            "unifil",
                            "vehicles",
                        ]
                    }
                )
            ]
        )
    )

    with caplog.at_level(logging.WARNING):
        result = service.categories_present("sample text", raw_message_id=42)

    assert result == [
        ExtractionCategoryKey.vehicles,
        ExtractionCategoryKey.unifil,
    ]
    assert any(
        "Dropped invalid extraction category" in record.message
        and "raw_message_id=42" in record.message
        and "attack" in record.message
        for record in caplog.records
    )
