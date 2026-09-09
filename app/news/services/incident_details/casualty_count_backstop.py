from __future__ import annotations

import logging
import re

from app.llm.dtos import CasualtyCountEvidence, ExtractionCasualties

logger = logging.getLogger(__name__)

CASUALTY_COUNT_FIELDS: tuple[str, ...] = (
    "total_deaths",
    "total_injuries",
    "deaths",
    "injuries",
    "male_deaths",
    "male_injuries",
    "female_deaths",
    "female_injuries",
    "children_deaths",
    "children_injuries",
)

_WESTERN_TO_ARABIC_INDIC = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")

_EXPLICIT_COUNT_WORDS: dict[str, dict[int, tuple[str, ...]]] = {
    "deaths": {
        1: ("شهيد", "شهيدة", "قتيل", "قتيلة"),
        2: ("شهيدان", "شهيدين", "قتيلان", "قتيلين"),
    },
    "injuries": {
        1: ("جريح", "جريحة", "مصاب", "مصابة"),
        2: ("جريحان", "جريحين", "مصابان", "مصابين"),
    },
}


def _digit_forms(value: int) -> tuple[str, str]:
    western = str(value)
    return western, western.translate(_WESTERN_TO_ARABIC_INDIC)


def text_contains_count_digit(text: str, value: int) -> bool:
    """True when *value* appears as a Western or Arabic-Indic numeral in *text*."""
    western, arabic_indic = _digit_forms(value)
    # Require digit-boundary so count=1 does not match inside 10/11/... .
    pattern = (
        rf"(?<![0-9٠-٩])(?:{re.escape(western)}|{re.escape(arabic_indic)})"
        rf"(?![0-9٠-٩])"
    )
    return bool(re.search(pattern, text))


def _evidence_contains_explicit_count(text: str, field: str, value: int) -> bool:
    if text_contains_count_digit(text, value):
        return True
    root_field = field.removeprefix("total_")
    words = _EXPLICIT_COUNT_WORDS.get(root_field, {}).get(value, ())
    return any(
        re.search(rf"(?<![\w]){re.escape(word)}(?![\w])", text)
        for word in words
    )


def apply_casualty_count_backstop(
    text: str,
    casualties: ExtractionCasualties,
    evidence: list[CasualtyCountEvidence] | None = None,
    *,
    raw_message_id: int | None = None,
) -> tuple[ExtractionCasualties, list[CasualtyCountEvidence]]:
    """Null casualty counts that lack a source digit and/or evidence_span.

    Safety net behind LLM extraction: a non-null count is kept only when its
    evidence span occurs in the source and contains either the explicit digit
    or an unambiguous Arabic singular/dual casualty form for 1 or 2.
    """
    evidence_by_field: dict[str, CasualtyCountEvidence] = {}
    for item in evidence or []:
        field = (item.field or "").strip()
        span = (item.evidence_span or "").strip()
        if field in CASUALTY_COUNT_FIELDS and span:
            evidence_by_field[field] = CasualtyCountEvidence(
                field=field,
                evidence_span=span,
            )

    values = casualties.model_dump(mode="python")
    kept_evidence: list[CasualtyCountEvidence] = []

    for field in CASUALTY_COUNT_FIELDS:
        value = values.get(field)
        if value is None:
            continue
        if not isinstance(value, int):
            values[field] = None
            continue

        field_evidence = evidence_by_field.get(field)
        span_is_grounded = (
            field_evidence is not None
            and field_evidence.evidence_span in text
        )
        has_explicit_count = (
            field_evidence is not None
            and _evidence_contains_explicit_count(
                field_evidence.evidence_span,
                field,
                value,
            )
        )
        if not span_is_grounded or not has_explicit_count:
            reason = (
                "missing_evidence_span"
                if field_evidence is None
                else "digit_not_in_source"
            )
            logger.warning(
                "casualty_count_backstop nulled field=%s value=%s reason=%s "
                "raw_message_id=%s",
                field,
                value,
                reason,
                raw_message_id,
            )
            values[field] = None
            continue

        kept_evidence.append(field_evidence)

    return ExtractionCasualties.model_validate(values), kept_evidence
