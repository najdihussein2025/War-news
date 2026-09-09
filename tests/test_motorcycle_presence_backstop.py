from __future__ import annotations

import json
from types import SimpleNamespace

from app.llm.dtos import ExtractionCategoryKey
from app.llm.services.ollama_category_detail_service import _ground_motorcycle_flag
from app.llm.services.ollama_presence_gate_service import OllamaPresenceGateService


def test_possessed_motorcycle_adds_vehicle_presence_when_model_misses_it() -> None:
    service = OllamaPresenceGateService(SimpleNamespace(model="test-model"))
    text = "استهدفتهما مسيّرة إسرائيلية على دراجتهما النارية"

    result = service._parse_response(
        json.dumps({"categories_present": [], "category_evidence": []}),
        raw_message_id=1213,
        post_text=text,
    )

    assert ExtractionCategoryKey.vehicles in result.categories_present
    evidence = next(
        item
        for item in result.category_evidence
        if item.category_key == ExtractionCategoryKey.vehicles
    )
    assert "دراجتهما" in evidence.evidence_span


def test_possessed_motorcycle_sets_moto_flag_when_model_misses_it() -> None:
    vehicles = _ground_motorcycle_flag(
        "استهدفتهما مسيّرة إسرائيلية على دراجتهما النارية",
        None,
    )

    assert vehicles is not None
    assert vehicles.moto is True
