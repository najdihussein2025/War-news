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


_GENERAL_RESPONSE_DEFAULT = ["بنت جبيل"]
_UNSET = object()


def _general_response(*, village_value: object = _UNSET) -> str:
    if village_value is _UNSET:
        village_value = _GENERAL_RESPONSE_DEFAULT
    return json.dumps(
        {
            "is_relevant": True,
            "village": village_value,
            "action_description": "غارة على المدينة",
            "casualties": {"injuries": 1},
        },
        ensure_ascii=False,
    )


def test_extract_tier1_skips_category_detail_calls() -> None:
    presence_gate = _PresenceGateStub(
        categories=[ExtractionCategoryKey.hospital]
    )
    category_detail = _CategoryDetailStub(details={})
    service = OllamaExtractionService(
        client=_client_for_model_contents([_general_response()]),
        presence_gate=presence_gate,
        category_detail=category_detail,
    )

    result = service.extract_tier1("sample text", raw_message_id=42)

    assert presence_gate.calls == 1
    assert category_detail.calls == []
    assert result.extraction_tier == 1
    assert result.presence_category_keys == [ExtractionCategoryKey.hospital]
    assert ExtractionCategoryKey.hospital not in result.categories
    assert ExtractionCategoryKey.casualty_demographics in result.categories


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
    assert result.village == ["بنت جبيل"]
    assert result.categories == {
        ExtractionCategoryKey.casualty_demographics: ExtractionCategory(
            did=None,
            name=None,
            casualties=ExtractionCasualties(injuries=1),
        )
    }


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
    assert len(result.categories) == 3
    assert ExtractionCategoryKey.casualty_demographics in result.categories
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
                        ],
                        "category_evidence": [
                            {
                                "category_key": "vehicles",
                                "evidence_span": "استهدفت سيارة على الطريق",
                            },
                            {
                                "category_key": "unifil",
                                "evidence_span": "UNIFIL patrol was targeted",
                            },
                        ],
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


def test_orchestration_isolates_malformed_category_detail(caplog) -> None:
    client = _client_for_model_contents(
        [
            _general_response(),
            "{malformed json",
            json.dumps(
                {
                    "did": "D",
                    "name": "Ø³ÙŠØ§Ø±Ø©",
                    "casualties": {"injuries": 1},
                },
                ensure_ascii=False,
            ),
        ]
    )
    presence_gate = _PresenceGateStub(
        categories=[
            ExtractionCategoryKey.health_center,
            ExtractionCategoryKey.vehicles,
        ]
    )
    service = OllamaExtractionService(
        client=client,
        presence_gate=presence_gate,
    )

    with caplog.at_level(logging.ERROR):
        result = service.extract("sample text", raw_message_id=42)

    assert set(result.categories) == {
        ExtractionCategoryKey.vehicles,
        ExtractionCategoryKey.casualty_demographics,
    }
    assert any(
        "Failed to extract category detail category=health_center raw_message_id=42"
        in record.message
        for record in caplog.records
    )


# ---------------------------------------------------------------------------
# Task-4: multi-village extraction tests
# ---------------------------------------------------------------------------


def test_comma_separated_village_string_is_parsed_into_list() -> None:
    """Model returns old-style comma-separated string → normalised to list."""
    presence_gate = _PresenceGateStub(categories=[])
    category_detail = _CategoryDetailStub(details={})
    service = OllamaExtractionService(
        client=_client_for_model_contents(
            [_general_response(village_value="كفرتبنيت, حرش عيتا الجبل")]
        ),
        presence_gate=presence_gate,
        category_detail=category_detail,
    )

    result = service.extract("sample text", raw_message_id=99)

    assert result.village == ["كفرتبنيت", "حرش عيتا الجبل"]


def test_json_array_village_is_used_as_is() -> None:
    """Model returns a JSON array of village names → used directly."""
    presence_gate = _PresenceGateStub(categories=[])
    category_detail = _CategoryDetailStub(details={})
    service = OllamaExtractionService(
        client=_client_for_model_contents(
            [_general_response(village_value=["بنت جبيل", "عيترون"])]
        ),
        presence_gate=presence_gate,
        category_detail=category_detail,
    )

    result = service.extract("sample text", raw_message_id=99)

    assert result.village == ["بنت جبيل", "عيترون"]


def test_null_village_from_model_is_preserved_as_none() -> None:
    """Model returns null → village is None."""
    presence_gate = _PresenceGateStub(categories=[])
    category_detail = _CategoryDetailStub(details={})
    service = OllamaExtractionService(
        client=_client_for_model_contents(
            [_general_response(village_value=None)]
        ),
        presence_gate=presence_gate,
        category_detail=category_detail,
    )

    result = service.extract("sample text", raw_message_id=99)

    assert result.village is None
