"""Parse/validate casualty_transitions extraction payloads (no live LLM)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.llm.dtos import CasualtyTransition, ExtractionResult
from app.llm.services.ollama_extraction_service import _RawExtractionResponse


GOLDEN_EXAMPLES = [
    {
        "label": "case2_death_only",
        "text": "توفي أحد الجرحى جراء إصابته في الغارة على بلدة عيتا الشعب",
        "payload": {
            "is_relevant": True,
            "village": ["عيتا الشعب"],
            "action_description": "توفي أحد الجرحى",
            "casualties": {"deaths": 1},
            "casualty_transitions": [
                {"from_status": "injured", "to_status": "deceased", "count": 1}
            ],
        },
        "expect_transition_count": 1,
    },
    {
        "label": "case1_restate_and_transition",
        "text": "بقي 3 جرحى وتوفي واحد من جرحى الغارة",
        "payload": {
            "is_relevant": True,
            "village": ["البلدة"],
            "action_description": "متابعة إصابات",
            "casualties": {"deaths": 1, "injuries": 3},
            "casualty_transitions": [
                {"from_status": "injured", "to_status": "deceased", "count": 1}
            ],
        },
        "expect_transition_count": 1,
    },
    {
        "label": "additive_no_transition",
        "text": "أصيب 5 جرحى جدد في قصف جديد على القرية",
        "payload": {
            "is_relevant": True,
            "village": ["القرية"],
            "action_description": "قصف",
            "casualties": {"injuries": 5},
            "casualty_transitions": [],
        },
        "expect_transition_count": 0,
    },
]


@pytest.mark.parametrize("example", GOLDEN_EXAMPLES, ids=[e["label"] for e in GOLDEN_EXAMPLES])
def test_golden_payload_parses_casualty_transitions(example: dict) -> None:
    response = _RawExtractionResponse.model_validate(example["payload"])
    assert len(response.casualty_transitions) == example["expect_transition_count"]


def test_legacy_payload_without_transitions_defaults_empty() -> None:
    response = _RawExtractionResponse.model_validate(
        {
            "is_relevant": True,
            "village": ["بلدة"],
            "action_description": "قصف",
            "casualties": {"injuries": 2},
        }
    )
    assert response.casualty_transitions == []


def test_extraction_result_round_trip_includes_transitions() -> None:
    payload = {
        "is_relevant": True,
        "village": ["x"],
        "action_description": "follow-up",
        "casualties": {"deaths": 1},
        "casualty_transitions": [
            {"from_status": "injured", "to_status": "deceased", "count": 1}
        ],
        "model": "test",
        "extracted_at": "2026-09-03T06:00:00+00:00",
    }
    result = ExtractionResult.model_validate(payload)
    assert len(result.casualty_transitions) == 1
    assert result.casualty_transitions[0] == CasualtyTransition(
        from_status="injured",
        to_status="deceased",
        count=1,
    )


def test_invalid_transition_rejected_by_schema() -> None:
    with pytest.raises(ValidationError):
        CasualtyTransition.model_validate(
            {"from_status": "injured", "to_status": "deceased", "count": 0}
        )


def test_prompt_validation_report() -> None:
    """Before/after summary for commit notes — schema now accepts transitions."""
    before_supported = 0
    after_supported = sum(
        1
        for example in GOLDEN_EXAMPLES
        if _RawExtractionResponse.model_validate(example["payload"]).casualty_transitions
        or example["expect_transition_count"] == 0
    )
    assert before_supported == 0
    assert after_supported == len(GOLDEN_EXAMPLES)
    print(
        json.dumps(
            {
                "before_transitions_field_supported": before_supported,
                "after_golden_examples_parsed": after_supported,
                "golden_example_count": len(GOLDEN_EXAMPLES),
            },
            ensure_ascii=False,
        )
    )
