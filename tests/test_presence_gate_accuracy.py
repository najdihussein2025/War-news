from __future__ import annotations

import json

import httpx

from app.core.ollama_client import OllamaChatClient
from app.llm.dtos import (
    ExtractionCasualties,
    ExtractionCategory,
    ExtractionCategoryKey,
)
from app.llm.services.ollama_extraction_service import OllamaExtractionService
from app.llm.services.ollama_presence_gate_service import OllamaPresenceGateService

# Real message excerpts from live recon (raw_message_ids 691363, 691378, 691430).
CIVIL_DEFENSE_RECOVERY_TEXT = (
    "الدفاع المدني في بيان: انتشال جثمان شهيد من أحد المباني في النبطية "
    "كان قد استشهد جراء غارة إسرائيلية سابقة"
)
BARE_VILLAGE_SHELLING_TEXT = "قصف مدفعيّ يستهدف بلدة ميس الجبل"
NEIGHBORHOOD_SHELLING_TEXT = "قصف مدفعي معادي يستهدف دوحة كفررمان"


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


def _empty_gate_response() -> str:
    return json.dumps({"categories_present": [], "category_evidence": []})


def _municipality_false_positive_response() -> str:
    return json.dumps(
        {
            "categories_present": ["municipality"],
            "category_evidence": [
                {
                    "category_key": "municipality",
                    "evidence_span": "قصف مدفعيّ يستهدف بلدة ميس الجبل",
                }
            ],
        },
        ensure_ascii=False,
    )


def _vehicles_false_positive_response() -> str:
    return json.dumps(
        {
            "categories_present": ["vehicles"],
            "category_evidence": [
                {
                    "category_key": "vehicles",
                    "evidence_span": "قصف مدفعي معادي يستهدف دوحة كفررمان",
                }
            ],
        },
        ensure_ascii=False,
    )


def test_emergency_civil_defense_added_for_civil_defense_statement() -> None:
    service = OllamaPresenceGateService(
        _client_for_model_contents([_empty_gate_response()])
    )

    result = service.evaluate(CIVIL_DEFENSE_RECOVERY_TEXT, raw_message_id=691363)

    assert ExtractionCategoryKey.emergency_civil_defense in result.categories_present
    civil_defense_evidence = next(
        item
        for item in result.category_evidence
        if item.category_key == ExtractionCategoryKey.emergency_civil_defense
    )
    assert "الدفاع المدني" in civil_defense_evidence.evidence_span


def test_municipality_dropped_for_bare_village_shelling() -> None:
    service = OllamaPresenceGateService(
        _client_for_model_contents([_municipality_false_positive_response()])
    )

    result = service.evaluate(BARE_VILLAGE_SHELLING_TEXT, raw_message_id=691378)

    assert ExtractionCategoryKey.municipality not in result.categories_present


def test_vehicles_dropped_for_neighborhood_shelling_without_vehicle_mention() -> None:
    service = OllamaPresenceGateService(
        _client_for_model_contents([_vehicles_false_positive_response()])
    )

    result = service.evaluate(NEIGHBORHOOD_SHELLING_TEXT, raw_message_id=691430)

    assert ExtractionCategoryKey.vehicles not in result.categories_present


def test_civil_defense_recovery_populates_casualty_demographics_from_root() -> None:
    general_response = json.dumps(
        {
            "is_relevant": True,
            "village": "النبطية",
            "action_description": "انتشال جثمان شهيد من أحد المباني",
            "casualties": {
                "deaths": 1,
                "total_deaths": 1,
                "male_deaths": 1,
            },
        },
        ensure_ascii=False,
    )
    civil_defense_detail = json.dumps(
        {
            "did": None,
            "name": "الدفاع المدني",
            "casualties": {},
        },
        ensure_ascii=False,
    )

    class _PresenceGateStub:
        def categories_present(
            self,
            post_text: str,
            raw_message_id: int | None = None,
        ) -> list[ExtractionCategoryKey]:
            return [ExtractionCategoryKey.emergency_civil_defense]

    service = OllamaExtractionService(
        client=_client_for_model_contents([general_response, civil_defense_detail]),
        presence_gate=_PresenceGateStub(),
    )

    result = service.extract(CIVIL_DEFENSE_RECOVERY_TEXT, raw_message_id=691363)

    assert ExtractionCategoryKey.emergency_civil_defense in result.categories
    assert ExtractionCategoryKey.casualty_demographics in result.categories
    assert result.casualties.deaths == 1
    assert result.categories[ExtractionCategoryKey.casualty_demographics].casualties == (
        ExtractionCasualties(deaths=1, total_deaths=1, male_deaths=1)
    )


def test_casualty_demographics_injected_even_when_presence_gate_empty() -> None:
    general_response = json.dumps(
        {
            "is_relevant": True,
            "village": "النبطية",
            "action_description": "انتشال جثمان شهيد",
            "casualties": {"deaths": 1, "total_deaths": 1},
        },
        ensure_ascii=False,
    )

    class _EmptyPresenceGateStub:
        def categories_present(
            self,
            post_text: str,
            raw_message_id: int | None = None,
        ) -> list[ExtractionCategoryKey]:
            return []

    service = OllamaExtractionService(
        client=_client_for_model_contents([general_response]),
        presence_gate=_EmptyPresenceGateStub(),
    )

    result = service.extract(CIVIL_DEFENSE_RECOVERY_TEXT, raw_message_id=691363)

    assert ExtractionCategoryKey.casualty_demographics in result.categories
    assert result.categories[ExtractionCategoryKey.casualty_demographics].casualties == (
        ExtractionCasualties(deaths=1, total_deaths=1)
    )
