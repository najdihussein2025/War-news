from __future__ import annotations

from typing import Any

from app.llm.dtos.extraction_dto import ExtractionCasualties
from app.news.services.incident_details.casualty_extraction_validation import (
    enforce_casualty_invariants,
)


TOTAL_FIELDS = ("total_deaths", "total_injuries")
DEMOGRAPHIC_FIELDS = (
    "male_d", "female_d", "children_d",
    "male_i", "female_i", "children_i",
)
CASUALTY_EDIT_FIELDS = TOTAL_FIELDS + DEMOGRAPHIC_FIELDS

_EXTRACTION_NAMES = {
    "total_deaths": "total_deaths",
    "total_injuries": "total_injuries",
    "male_d": "male_deaths",
    "female_d": "female_deaths",
    "children_d": "children_deaths",
    "male_i": "male_injuries",
    "female_i": "female_injuries",
    "children_i": "children_injuries",
}


class AdminCasualtyValidationError(ValueError):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


def validate_admin_casualties(values: dict[str, Any]) -> dict[str, int | None]:
    """Strictly validate an administrator's eight casualty values.

    The pipeline invariant enforcer is deliberately corrective. Admin input is
    different: if correction would be required, reject it and explain why.
    """
    cleaned: dict[str, int | None] = {}
    for field in CASUALTY_EDIT_FIELDS:
        value = values.get(field)
        if value is None or value == "":
            cleaned[field] = None
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise AdminCasualtyValidationError(
                field, f"{field} must be a non-negative integer or null."
            )
        cleaned[field] = value

    extraction = ExtractionCasualties(**{
        extraction_name: cleaned[field]
        for field, extraction_name in _EXTRACTION_NAMES.items()
    })
    _normalized, adjustments = enforce_casualty_invariants(extraction)
    raised = next(
        (item for item in adjustments if item.get("reason") == "raised_to_breakdown_sum"),
        None,
    )
    if raised:
        outcome = "deaths" if raised["field"] == "total_deaths" else "injuries"
        total = cleaned[f"total_{outcome}"]
        breakdown = sum(
            cleaned[field] or 0
            for field in (
                ("male_d", "female_d", "children_d")
                if outcome == "deaths"
                else ("male_i", "female_i", "children_i")
            )
        )
        raise AdminCasualtyValidationError(
            f"total_{outcome}",
            f"Total {outcome} ({total if total is not None else 'null'}) must be at least the demographic breakdown ({breakdown}).",
        )
    return cleaned
