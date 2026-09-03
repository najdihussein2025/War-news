from types import SimpleNamespace
from unittest.mock import MagicMock

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
