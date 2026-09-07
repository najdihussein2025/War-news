from types import SimpleNamespace
from unittest.mock import MagicMock

from app.llm.dtos import ExtractionCasualties, ExtractionCategoryKey
from app.llm.services.cnrs_extraction_fallback import CnrsExtractionFallback


def test_uses_cnrs_location_and_subtype_without_calling_ollama(monkeypatch) -> None:
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

    result = CnrsExtractionFallback(ollama).extract_tier1("text", 42)

    assert result.village == ["المنصوري"]
    assert result.action_description == "Artillery Shelling"
    assert result.model == "cnrs_provided"
    ollama.extract_tier1.assert_not_called()


def test_unsupported_cnrs_subtype_does_not_block_on_ollama(monkeypatch) -> None:
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

    result = CnrsExtractionFallback(ollama).extract_tier1("text", 43)

    assert result.is_relevant is False
    ollama.extract_tier1.assert_not_called()


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
