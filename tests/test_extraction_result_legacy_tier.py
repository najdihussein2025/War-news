from __future__ import annotations

from datetime import datetime, timezone

from app.llm.dtos.extraction_dto import ExtractionResult


def test_legacy_empty_categories_default_to_tier_one() -> None:
    result = ExtractionResult.model_validate(
        {
            "is_relevant": True,
            "categories": {},
            "model": "test",
            "extracted_at": datetime(2026, 8, 18, tzinfo=timezone.utc),
        }
    )

    assert result.extraction_tier == 1


def test_legacy_populated_categories_default_to_tier_two() -> None:
    result = ExtractionResult.model_validate(
        {
            "is_relevant": True,
            "categories": {
                "hospital": {
                    "did": "D",
                    "name": "مستشفى",
                    "casualties": None,
                }
            },
            "model": "test",
            "extracted_at": datetime(2026, 8, 18, tzinfo=timezone.utc),
        }
    )

    assert result.extraction_tier == 2


def test_explicit_extraction_tier_is_preserved() -> None:
    result = ExtractionResult.model_validate(
        {
            "is_relevant": True,
            "categories": {},
            "extraction_tier": 1,
            "model": "test",
            "extracted_at": datetime(2026, 8, 18, tzinfo=timezone.utc),
        }
    )

    assert result.extraction_tier == 1
