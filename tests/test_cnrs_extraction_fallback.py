from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.llm.dtos import (
    ExtractionCasualties,
    ExtractionCategory,
    ExtractionCategoryKey,
    ExtractionResult,
    ExtractionVehicleDetails,
    VillageRole,
    VillageRoleEntry,
)
from app.llm.services.cnrs_extraction_fallback import CnrsExtractionFallback


def _llm_result(**updates) -> ExtractionResult:
    result = ExtractionResult(
        is_relevant=True,
        village=["اسم مستخرج"],
        village_roles=[
            VillageRoleEntry(village="اسم مستخرج", role=VillageRole.target)
        ],
        action_description="LLM action",
        casualties=ExtractionCasualties(deaths=2, injuries=3),
        categories={
            ExtractionCategoryKey.hospital: ExtractionCategory(name="مستشفى")
        },
        presence_category_keys=[ExtractionCategoryKey.hospital],
        extraction_tier=2,
        model="qwen-test",
        extracted_at=datetime.now(timezone.utc),
    )
    return result.model_copy(update=updates)


def test_uses_full_llm_details_with_cnrs_location_and_subtype(monkeypatch) -> None:
    message = SimpleNamespace(
        cnrs_classification={
            "include": True,
            "location": "المنصوري",
            "event_subtype": "artillery",
        },
        raw_text="قصف مدفعي على المنصوري",
    )
    session = MagicMock()
    session.get.return_value = message
    session.__enter__.return_value = session
    monkeypatch.setattr(
        "app.llm.services.cnrs_extraction_fallback.SessionLocal",
        lambda: session,
    )
    ollama = MagicMock()
    ollama.extract.return_value = _llm_result()

    result = CnrsExtractionFallback(ollama).extract_tier1("text", 42)

    assert result.village == ["المنصوري"]
    assert result.village_roles[0].village == "المنصوري"
    assert result.action_description == "Artillery Shelling"
    assert result.casualties == ExtractionCasualties(deaths=2, injuries=3)
    assert ExtractionCategoryKey.hospital in result.categories
    assert result.model == "qwen-test"
    assert result.extraction_tier == 2
    ollama.extract.assert_called_once_with("text", 42)


def test_cnrs_motorcycle_attack_preserves_vehicle_category(monkeypatch) -> None:
    message = SimpleNamespace(
        cnrs_classification={
            "include": True,
            "location": "زبدين",
            "event_subtype": "airstrike",
        },
        raw_text="الطيران المسير المعادي أغار على دراجة نارية في بلدة زبدين",
    )
    session = MagicMock()
    session.get.return_value = message
    session.__enter__.return_value = session
    monkeypatch.setattr(
        "app.llm.services.cnrs_extraction_fallback.SessionLocal",
        lambda: session,
    )

    ollama = MagicMock()
    ollama.extract.return_value = _llm_result(
        categories={
            ExtractionCategoryKey.vehicles: ExtractionCategory(
                vehicles=ExtractionVehicleDetails(car=True, moto=False)
            )
        },
        presence_category_keys=[ExtractionCategoryKey.vehicles],
    )

    result = CnrsExtractionFallback(ollama).extract_tier1(message.raw_text, 44)

    vehicles = result.categories[ExtractionCategoryKey.vehicles].vehicles
    assert vehicles is not None
    assert vehicles.car is True
    assert vehicles.moto is True
    assert result.presence_category_keys == [ExtractionCategoryKey.vehicles]


def test_unsupported_cnrs_subtype_preserves_llm_result(monkeypatch) -> None:
    message = SimpleNamespace(
        cnrs_classification={
            "include": True,
            "location": "البقاع الغربي",
            "event_subtype": "storm_damage",
        },
        raw_text="عاصفة في البقاع الغربي",
    )
    session = MagicMock()
    session.get.return_value = message
    session.__enter__.return_value = session
    monkeypatch.setattr(
        "app.llm.services.cnrs_extraction_fallback.SessionLocal",
        lambda: session,
    )
    ollama = MagicMock()
    ollama.extract.return_value = _llm_result(
        is_relevant=True,
        action_description="Flooding",
    )

    result = CnrsExtractionFallback(ollama).extract_tier1("text", 43)

    assert result.is_relevant is True
    assert result.action_description == "Flooding"
    assert result.village == ["البقاع الغربي"]
    ollama.extract.assert_called_once_with("text", 43)


def test_multi_village_llm_targets_are_not_collapsed(monkeypatch) -> None:
    message = SimpleNamespace(
        cnrs_classification={
            "include": True,
            "location": "النبطية",
            "event_subtype": "airstrike",
        },
        raw_text="غارات على النبطية وكفرمان",
    )
    session = MagicMock()
    session.get.return_value = message
    session.__enter__.return_value = session
    monkeypatch.setattr(
        "app.llm.services.cnrs_extraction_fallback.SessionLocal",
        lambda: session,
    )
    ollama = MagicMock()
    ollama.extract.return_value = _llm_result(
        village=["النبطية", "كفرمان"],
        village_roles=[
            VillageRoleEntry(village="النبطية", role=VillageRole.target),
            VillageRoleEntry(village="كفرمان", role=VillageRole.target),
        ],
    )

    result = CnrsExtractionFallback(ollama).extract_tier1("text", 45)

    assert result.village == ["النبطية", "كفرمان"]
    assert [entry.village for entry in result.village_roles] == [
        "النبطية",
        "كفرمان",
    ]


def test_full_llm_failure_is_propagated_for_pipeline_retry(monkeypatch) -> None:
    message = SimpleNamespace(
        cnrs_classification={
            "include": True,
            "location": "زبدين",
            "event_subtype": "airstrike",
        },
        raw_text="غارة على زبدين",
    )
    session = MagicMock()
    session.get.return_value = message
    session.__enter__.return_value = session
    monkeypatch.setattr(
        "app.llm.services.cnrs_extraction_fallback.SessionLocal",
        lambda: session,
    )
    ollama = MagicMock()
    ollama.extract.side_effect = TimeoutError("Ollama timeout")

    with pytest.raises(TimeoutError, match="Ollama timeout"):
        CnrsExtractionFallback(ollama).extract_tier1("text", 46)


def test_non_cnrs_message_keeps_normal_tier1_path(monkeypatch) -> None:
    session = MagicMock()
    session.get.return_value = SimpleNamespace(cnrs_classification=None)
    session.__enter__.return_value = session
    monkeypatch.setattr(
        "app.llm.services.cnrs_extraction_fallback.SessionLocal",
        lambda: session,
    )
    ollama = MagicMock()
    ollama.extract_tier1.return_value = _llm_result(extraction_tier=1)

    result = CnrsExtractionFallback(ollama).extract_tier1("text", 47)

    assert result.extraction_tier == 1
    ollama.extract_tier1.assert_called_once_with("text", 47)
    ollama.extract.assert_not_called()


def test_tier2_details_delegate_to_wrapped_extractor() -> None:
    ollama = MagicMock()
    ollama.extract_tier2_details.return_value = {
        ExtractionCategoryKey.vehicles: MagicMock()
    }

    result = CnrsExtractionFallback(ollama).extract_tier2_details(
        post_text="text",
        presence_category_keys=[ExtractionCategoryKey.vehicles],
        root_casualties=ExtractionCasualties(),
        raw_message_id=42,
    )

    assert result == ollama.extract_tier2_details.return_value
    ollama.extract_tier2_details.assert_called_once_with(
        post_text="text",
        presence_category_keys=[ExtractionCategoryKey.vehicles],
        root_casualties=ExtractionCasualties(),
        raw_message_id=42,
    )
