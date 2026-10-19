"""Deterministic safety checks for LLM casualty extraction output."""

from __future__ import annotations

import re
from typing import Any

from app.core.text_normalization import normalize_arabic_text
from app.llm.dtos import CasualtyCountEvidence, ExtractionCasualties


_FIELDS = (
    "deaths", "injuries", "total_deaths", "total_injuries",
    "male_deaths", "male_injuries", "female_deaths", "female_injuries",
    "children_deaths", "children_injuries",
)
_OUTCOME_FIELDS = {
    "deaths": ("deaths", "total_deaths", "male_deaths", "female_deaths", "children_deaths"),
    "injuries": ("injuries", "total_injuries", "male_injuries", "female_injuries", "children_injuries"),
}
_DISALLOWED_EVIDENCE = (
    "صفحه", "قناه", "توقيع", "الاعلامي الشهيد", "ذكرى", "الذكرى",
    "جنازه", "تشييع", "رحم الله الشهداء", "رحم الله الشهيد", "مضى على",
)


def _reason_for_span(body: str, span: str) -> str | None:
    normalized_body = normalize_arabic_text(body or "")
    normalized_span = normalize_arabic_text(span or "")
    if not normalized_span or normalized_span not in normalized_body:
        return "evidence_not_in_cleaned_body"
    if any(
        normalize_arabic_text(token) in normalized_span
        for token in _DISALLOWED_EVIDENCE
    ):
        return "header_or_memorial_evidence"
    return None


_PRAYER_TOKENS = ("رحم الله الشهداء", "رحم الله الشهيد")


def line_rejection_reason(body: str, span: str, *, check_span_tokens: bool = True) -> str | None:
    """Like the span check, but also rejects a span that sits on a header/memorial line.

    «صفحة الإعلامي الشهيد علي شعيب» may be on its own line while the counted word
    (الشهيد) is all the span contains; the span alone looks innocent. A prayer
    elsewhere on the line does not disqualify a real report, so line-level
    matching ignores the prayer tokens. ``check_span_tokens=False`` is for broad
    clauses (recompute claims) where only presence in the body and the line check matter.
    """
    normalized_body = normalize_arabic_text(body or "")
    normalized_span = normalize_arabic_text(span or "")
    if not normalized_span or normalized_span not in normalized_body:
        return "evidence_not_in_cleaned_body"
    if check_span_tokens:
        reason = _reason_for_span(body, span)
        if reason is not None:
            return reason
    prayer = {normalize_arabic_text(token) for token in _PRAYER_TOKENS}
    line_tokens = [
        normalize_arabic_text(token) for token in _DISALLOWED_EVIDENCE
        if normalize_arabic_text(token) not in prayer
    ]
    for line in re.split(r"[\r\n]+", normalized_body):
        if normalized_span in line and any(token in line for token in line_tokens):
            return "header_or_memorial_evidence"
    return None


def validate_casualty_evidence(
    body: str,
    casualties: ExtractionCasualties,
    evidence: list[CasualtyCountEvidence],
) -> tuple[ExtractionCasualties, list[CasualtyCountEvidence], list[dict[str, str]]]:
    """Drop values unsupported by literal, body-scoped casualty evidence."""
    values = casualties.model_dump(mode="python")
    evidence_by_field = {item.field: item for item in evidence if item.field in _FIELDS}
    kept: list[CasualtyCountEvidence] = []
    dropped: list[dict[str, str]] = []
    dropped_fields: set[str] = set()
    for item in evidence:
        if item.field not in _FIELDS:
            continue
        reason = _reason_for_span(body, item.evidence_span)
        if reason is None:
            kept.append(item)
            continue
        dropped.append({"field": item.field, "reason": reason, "evidence_span": item.evidence_span})
        dropped_fields.add(item.field)

    for field in dropped_fields:
        values[field] = None
        # A generic count and its roll-up represent the same claim.
        if field == "deaths":
            values["total_deaths"] = None
        elif field == "injuries":
            values["total_injuries"] = None
        elif field == "total_deaths":
            values["deaths"] = None
        elif field == "total_injuries":
            values["injuries"] = None
    # A non-null field without any evidence is not accepted.  This intentionally
    # applies only where the extraction supplied an evidence list at all, so
    # legacy payloads can still be revalidated/repaired by their source parser.
    if evidence:
        for field in _FIELDS:
            if values.get(field) is not None and field not in evidence_by_field:
                values[field] = None
                dropped.append({"field": field, "reason": "missing_evidence_span", "evidence_span": ""})
    return ExtractionCasualties.model_validate(values), kept, dropped


def enforce_casualty_invariants(
    casualties: ExtractionCasualties,
    *,
    evidence_fields: set[str] | None = None,
) -> tuple[ExtractionCasualties, list[dict[str, Any]]]:
    """Normalize counts without guessing demographics or retaining negatives."""
    values = casualties.model_dump(mode="python")
    adjustments: list[dict[str, Any]] = []
    for field in _FIELDS:
        if isinstance(values.get(field), int) and values[field] < 0:
            adjustments.append({"field": field, "reason": "negative_count_dropped", "old": values[field]})
            values[field] = None

    for outcome, fields in _OUTCOME_FIELDS.items():
        base, total, male, female, children = fields
        demographics = (male, female, children)
        # Generic/untagged counts are totals only; no demographic is inferred.
        if evidence_fields is not None and values.get(base) is not None:
            # Only a field with its own explicit evidence is demographic data.
            # This makes a child claim take precedence over an ungrounded
            # female/male guess for the same untyped main count.
            for field in demographics:
                if values.get(field) is not None and field not in evidence_fields:
                    adjustments.append({"field": field, "reason": "untyped_count_breakdown_dropped"})
                    values[field] = None
        breakdown = sum(value for field in demographics if isinstance((value := values.get(field)), int))
        current_total = values.get(total)
        base_value = values.get(base)
        required_total = max(
            breakdown,
            base_value if isinstance(base_value, int) else 0,
            current_total if isinstance(current_total, int) else 0,
        )
        if required_total > 0 and current_total != required_total:
            adjustments.append({"field": total, "reason": "raised_to_breakdown_sum", "old": current_total, "new": required_total})
            values[total] = required_total
    return ExtractionCasualties.model_validate(values), adjustments
