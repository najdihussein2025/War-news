from __future__ import annotations

import logging

from app.core.llm_knowledge.source_headers import header_spans, strip_source_headers
from app.llm.dtos import CasualtyCountEvidence, ExtractionCasualties
from app.news.services.incident_details.casualty_text import (
    bare_token_lacks_event_context,
    field_kind,
    find_explicit_none,
    find_supporting_mention,
    has_vague_quantifier,
    strike_list_number_spans,
)

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


def _unsupported_detail(span: str, source: str, field: str) -> str:
    """Why a grounded evidence span failed; for logs only."""
    kind, _ = field_kind(field)
    if any(span in entry or entry in span for entry in strike_list_number_spans(source)):
        return "strike_count_list"
    if has_vague_quantifier(span, kind):
        return "vague_quantifier"
    return "no_adjacent_casualty_noun"


def apply_casualty_count_backstop(
    text: str,
    casualties: ExtractionCasualties,
    evidence: list[CasualtyCountEvidence] | None = None,
    *,
    raw_message_id: int | None = None,
) -> tuple[ExtractionCasualties, list[CasualtyCountEvidence]]:
    """Null casualty counts that the source does not explicitly state.

    Safety net behind LLM extraction. A non-null count is kept only when the
    value is written next to a matching casualty noun (a digit, a spelled-out
    number, or an Arabic singular/dual form — see ``casualty_text``):

    * inside its grounded ``evidence_span``; or
    * when the span is missing or not in the source, somewhere in the source,
      in which case that local phrase becomes the evidence span.

    Dates, times, URLs, «place (n)» strike-count entries and vague quantifiers
    («وقوع إصابات»، «عشرات الجرحى») never validate a count. A count of 0 is
    kept only when the text says so explicitly («دون تسجيل إصابات»).

    Channel/page headers are removed first: a span that sits inside one, or a bare
    «شهيد» / «الشهيد» token with no event context in the body, is rejected (NULL).
    """
    text = strip_source_headers(text)
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
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            values[field] = None
            continue

        field_evidence = evidence_by_field.get(field)
        if field_evidence is not None and header_spans(field_evidence.evidence_span):
            # The model quoted the channel name: never evidence.
            field_evidence = None
        span_is_grounded = (
            field_evidence is not None and field_evidence.evidence_span in text
        )
        kind, _ = field_kind(field)

        if value == 0:
            phrase = (
                find_explicit_none(field_evidence.evidence_span, kind)
                if span_is_grounded
                else None
            )
            if phrase is not None:
                kept_evidence.append(field_evidence)
                continue
            phrase = find_explicit_none(text, kind)
            if phrase is not None:
                kept_evidence.append(
                    CasualtyCountEvidence(field=field, evidence_span=phrase)
                )
                continue
            reason = "zero_without_explicit_none"
        elif span_is_grounded:
            if find_supporting_mention(field_evidence.evidence_span, field, value):
                if not bare_token_lacks_event_context(text, field_evidence.evidence_span):
                    kept_evidence.append(field_evidence)
                    continue
                reason = "bare_token_no_event_context"
            else:
                # A grounded span that does not state the value stays nulled even
                # if another clause of the message has that number.
                reason = "digit_not_in_source detail=" + _unsupported_detail(
                    field_evidence.evidence_span, text, field
                )
        else:
            # Missing or ungrounded span (import/LLM evidence gaps): keep the
            # value only if the source states it next to a matching noun.
            mention = find_supporting_mention(text, field, value)
            if mention is not None and not bare_token_lacks_event_context(text, mention.text):
                kept_evidence.append(
                    CasualtyCountEvidence(field=field, evidence_span=mention.text)
                )
                continue
            reason = (
                "bare_token_no_event_context"
                if mention is not None
                else "missing_evidence_span"
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

    return ExtractionCasualties.model_validate(values), kept_evidence
