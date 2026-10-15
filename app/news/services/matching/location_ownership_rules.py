"""Deterministic ownership rules for local places that models may mis-scope.

Canonical alias-to-village mappings remain data-driven in
``village_location_aliases``.  This module only repairs extraction mistakes
that happen before the normal alias resolver runs, such as treating a caza
name as the target instead of a local place named in the same report.
"""

import re
from dataclasses import dataclass

from app.core.text_normalization import normalize_arabic_text, village_match_key
from app.llm.dtos import ExtractionResult


@dataclass(frozen=True)
class LocationOwnershipRule:
    source_name: str
    replacement_name: str
    replace_extracted_names: frozenset[str]
    required_source_phrases: tuple[str, ...] = ()


_RULES = (
    LocationOwnershipRule(
        source_name="الدبشة",
        replacement_name="الدبشة",
        replace_extracted_names=frozenset(
            village_match_key(value) for value in ("النبطية", "مدينة النبطية")
        ),
        required_source_phrases=("قضاء النبطية",),
    ),
)


def _contains_arabic_name(text: str, name: str) -> bool:
    escaped = re.escape(normalize_arabic_text(name))
    return re.search(rf"(?<![\u0621-\u064a]){escaped}(?![\u0621-\u064a])", text) is not None


def apply_location_ownership_rules(
    extraction_result: ExtractionResult,
    raw_text: str | None,
) -> ExtractionResult:
    """Repair known district/local-place extraction collisions.

    The returned local name is still resolved by the regular alias repository;
    this function deliberately does not duplicate ACS IDs or alias ownership.
    """
    normalized_source = normalize_arabic_text(raw_text or "")
    if not normalized_source:
        return extraction_result

    applicable = [
        rule
        for rule in _RULES
        if _contains_arabic_name(normalized_source, rule.source_name)
        and all(
            normalize_arabic_text(phrase) in normalized_source
            for phrase in rule.required_source_phrases
        )
    ]
    if not applicable:
        return extraction_result

    def corrected_name(value: str) -> str:
        key = village_match_key(value)
        for rule in applicable:
            if key in rule.replace_extracted_names:
                return rule.replacement_name
        return value

    villages = (
        [corrected_name(value) for value in extraction_result.village]
        if extraction_result.village
        else extraction_result.village
    )
    roles = [
        role.model_copy(update={"village": corrected_name(role.village)})
        for role in extraction_result.village_roles
    ]
    sub_events = [
        sub_event.model_copy(
            update={
                "locations": [
                    location.model_copy(
                        update={"village": corrected_name(location.village)}
                    )
                    for location in sub_event.locations
                ]
            }
        )
        for sub_event in extraction_result.sub_events
    ]
    return extraction_result.model_copy(
        update={"village": villages, "village_roles": roles, "sub_events": sub_events}
    )
