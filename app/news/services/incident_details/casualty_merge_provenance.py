"""One guard for every path that adopts casualty values from a linked message.

Fast-path duplicate merge, story/revision merge, ``merge_existing`` and the
recompute writer may take casualty values from another raw message only if

1. the evidence is in that message's cleaned body (``casualty_extraction_validation``),
2. it describes the same event, and
3. it is at the same village.

Anything else keeps the incident's own values; the rejection reason is returned
so the caller can write it to the audit row.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.llm_knowledge.message_text import clean_message_text
from app.core.text_normalization import normalize_arabic_text
from app.news.services.incident_details.casualty_extraction_validation import (
    line_rejection_reason,
)
from app.news.services.incident_details.casualty_text import (
    field_kind,
    find_count_mentions,
    strip_page_header,
)

# incoming merge key -> extraction field name understood by find_supporting_mention
_BASE_FIELDS = (("deaths", "deaths"), ("injuries", "injuries"))
_TOTAL_FIELDS = (("total_deaths", "deaths"), ("total_injuries", "injuries"))
_DEMOGRAPHIC_FIELDS = (
    ("male_d", "male_deaths"), ("male_i", "male_injuries"),
    ("female_d", "female_deaths"), ("female_i", "female_injuries"),
    ("children_d", "children_deaths"), ("children_i", "children_injuries"),
)
CASUALTY_KEYS = tuple(k for k, _ in _BASE_FIELDS + _TOTAL_FIELDS + _DEMOGRAPHIC_FIELDS)
_STATUS_KEYS = (
    "casualty_status", "casualty_deaths_status", "casualty_injuries_status",
    "casualty_status_remaining_total", "casualty_is_preliminary",
    "casualty_status_evidence", "casualty_transitions",
)


@dataclass(frozen=True)
class ProvenanceDecision:
    """``values`` are the incoming casualty keys that may be adopted (others dropped)."""

    values: dict[str, Any]
    rejected: list[dict[str, Any]] = field(default_factory=list)
    status_allowed: bool = True
    # Transitions carry their own backstop; only another event/village invalidates them.
    event_mismatch: bool = False

    @property
    def clean(self) -> bool:
        return not self.rejected

    def apply_to(self, incoming: dict[str, Any]) -> dict[str, Any]:
        """Copy of ``incoming`` with unproven casualty values (and their status) removed."""
        merged = dict(incoming)
        merged.update(self.values)
        if not self.status_allowed:
            for key in _STATUS_KEYS:
                if key in merged and (key != "casualty_transitions" or self.event_mismatch):
                    merged[key] = [] if key == "casualty_transitions" else None
        return merged


def cleaned_body(raw_text: str | None) -> str:
    return strip_page_header(clean_message_text(raw_text or ""))


def village_rejection_reason(match_result: dict[str, Any] | None, incident_village_id: int | None) -> str | None:
    """``different_village`` when the message explicitly targets other villages only."""
    targets = {
        item.get("matched_village_id")
        for item in (match_result or {}).get("village_matches") or []
        if isinstance(item, dict)
        and item.get("village_role", "target") == "target"
        and item.get("matched_village_id") is not None
    }
    if incident_village_id is not None and targets and incident_village_id not in targets:
        return "different_village"
    return None


def quote_rejection_reason(body: str, quote: str, *, clause: bool = False) -> str | None:
    if not normalize_arabic_text(body or "") or not (quote or "").strip():
        return "evidence_not_in_cleaned_body"
    return line_rejection_reason(body, quote, check_span_tokens=not clause)


def vet_incoming_casualties(
    raw_message: Any | None,
    incoming: dict[str, Any],
    *,
    incident_village_id: int | None,
    same_event: bool = True,
) -> ProvenanceDecision:
    """Decide which incoming casualty values may be adopted from ``raw_message``."""
    present = {k: incoming.get(k) for k in CASUALTY_KEYS if isinstance(incoming.get(k), int)
               and not isinstance(incoming.get(k), bool)}
    if raw_message is None or not present:
        # No linked message to vet, or nothing to adopt.
        return ProvenanceDecision(values={k: incoming.get(k) for k in CASUALTY_KEYS if k in incoming})
    positive_present = {k: v for k, v in present.items() if v > 0}
    raw_id = getattr(raw_message, "id", None)

    def reject_all(reason: str) -> ProvenanceDecision:
        rejected = [{"field": k, "value": v, "reason": reason, "raw_message_id": raw_id} for k, v in present.items()]
        values = {k: None for k in CASUALTY_KEYS if k in incoming}
        return ProvenanceDecision(values=values, rejected=rejected, status_allowed=False, event_mismatch=True)

    if not same_event:
        return reject_all("different_event")
    village_reason = village_rejection_reason(getattr(raw_message, "match_result", None), incident_village_id)
    if village_reason:
        return reject_all(village_reason)
    if not positive_present:
        # Explicit zeros need an explicit "no casualties" statement; leave them to the caller.
        return ProvenanceDecision(values={k: incoming.get(k) for k in CASUALTY_KEYS if k in incoming})

    raw_text = getattr(raw_message, "raw_text", None)
    body = cleaned_body(raw_text if isinstance(raw_text, str) else "")
    values = {k: incoming.get(k) for k in CASUALTY_KEYS if k in incoming}
    rejected: list[dict[str, Any]] = []
    # Every count mention in the cleaned body, minus those on header/memorial lines.
    # A merged value may legitimately be a sum of several mentions, so the test is
    # "this body states casualties of this kind", not "one mention equals the value".
    valid, header_only = [], False
    for mention in find_count_mentions(body) if body else []:
        if quote_rejection_reason(body, mention.text) is None:
            valid.append(mention)
        else:
            header_only = True

    def reason_for(key: str, extraction_field: str) -> str | None:
        kind, group = field_kind(extraction_field)
        for mention in valid:
            if group is None and mention.kind == kind and mention.counts_total:
                return None
            if group is not None and mention.gender_or_group == group and mention.kind in (None, kind):
                return None
        if not body:
            return "evidence_not_in_cleaned_body"
        return "header_or_memorial_evidence" if header_only else "evidence_not_in_cleaned_body"

    for key, extraction_field in _BASE_FIELDS + _TOTAL_FIELDS + _DEMOGRAPHIC_FIELDS:
        if key not in present or present[key] <= 0:
            continue
        reason = reason_for(key, extraction_field)
        if reason is not None:
            rejected.append({"field": key, "value": present[key], "reason": reason, "raw_message_id": raw_id})
            values[key] = None
    survives = any(values.get(k) for k in CASUALTY_KEYS)
    return ProvenanceDecision(values=values, rejected=rejected, status_allowed=survives or not rejected)


def filter_validated_claims(claims, cleaned_by_source: dict[int, str]):
    """Split recompute claims into (kept, rejected) using the body of each claim's source."""
    kept, rejected = [], []
    for claim in claims:
        body = cleaned_by_source.get(claim.raw_message_id, "")
        reason = None
        for quote in claim.quotes.values():
            reason = quote_rejection_reason(body, quote, clause=True)
            if reason:
                break
        if reason:
            rejected.append({"raw_message_id": claim.raw_message_id, "village_id": claim.village_id,
                             "reason": reason, "quotes": list(claim.quotes.values())})
        else:
            kept.append(claim)
    return kept, rejected
