from datetime import datetime, timezone

from app.llm.dtos import CasualtyScope, ExtractionResult
from app.llm.services.ollama_extraction_service import COMBINED_TIER1_RESPONSE_SCHEMA


def test_extraction_result_defaults_casualty_scope_for_legacy_payload() -> None:
    result = ExtractionResult.model_validate(
        {
            "is_relevant": True,
            "model": "test",
            "extracted_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    assert result.casualty_scope == CasualtyScope.unspecified
    assert result.casualty_scope_evidence is None


def test_combined_tier1_schema_requires_casualty_scope_and_evidence() -> None:
    required = set(COMBINED_TIER1_RESPONSE_SCHEMA["required"])

    assert {"casualty_scope", "casualty_scope_evidence"} <= required
    assert COMBINED_TIER1_RESPONSE_SCHEMA["properties"]["casualty_scope"] == {
        "type": "string",
        "enum": [
            "per_village_exact",
            "bulletin_aggregate",
            "unspecified",
        ],
    }
