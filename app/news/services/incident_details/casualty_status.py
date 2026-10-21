"""Deterministic per-message casualty status derivation.

This module never calls an LLM or accesses a database. It combines the source
wording with the final extracted counts. For a multi-location bulletin, a
known per-location count remains visible while ``remaining_total`` records any
unallocated remainder from a larger bulletin total.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from app.llm.dtos import ExtractionCasualties
from app.news.services.incident_details.casualty_text import (
    DEATHS,
    INJURIES,
    find_count_mentions,
    find_explicit_none,
    has_casualty_wording,
    has_explicit_none,
    has_vague_quantifier,
    is_obituary,
    mentions_named_victim,
    normalize_casualty_text,
    sentences,
    strip_page_header,
)
from app.news.services.incident_details.casualty_count_fill import (
    infer_count_from_count_words,
)

CasualtyStatusCode = Literal[
    "none_mentioned",
    "explicit_none",
    "exact",
    "count_missing",
    "aggregate_only",
]

_STATUS_PRIORITY = {
    "none_mentioned": 0,
    "explicit_none": 1,
    "exact": 2,
    "count_missing": 3,
    "aggregate_only": 4,
}
_PRELIMINARY_PATTERNS = tuple(
    re.compile(normalize_casualty_text(pattern))
    for pattern in (
        r"حصيلة\s+(?:أولية|مؤقتة|غير\s+نهائية)",
        r"(?:المعلومات|معلومات)\s+الأولية\s+عن\s+(?:سقوط|استشهاد|إصابة)",
        r"(?:ارتفاع|ارتفع)\s+(?:عدد|حصيلة)",
        r"(?:تحديث|مراجعة|تصحيح)\s+(?:في\s+)?الحصيلة",
    )
)
_FINAL_TOLL = re.compile(normalize_casualty_text(r"حصيلة\s+نهائية"))


@dataclass(frozen=True)
class CasualtyStatusResult:
    status: CasualtyStatusCode
    deaths_status: CasualtyStatusCode
    injuries_status: CasualtyStatusCode
    is_preliminary: bool
    evidence: str | None
    remaining_total: dict[str, int]


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _positive_counts(value: Any, kind: str) -> list[int]:
    fields = (
        kind,
        f"total_{kind}",
        f"male_{kind}",
        f"female_{kind}",
        f"children_{kind}",
    )
    values = []
    for field in fields:
        count = _get(value, field)
        if isinstance(count, int) and not isinstance(count, bool) and count > 0:
            values.append(count)
    return values


def _locations_with_counts(
    village_roles: Any,
    sub_events: Any,
    kind: str,
) -> list[tuple[str, int]]:
    per_location: dict[str, int] = {}
    for role in village_roles or ():
        if _get(role, "role", "target") not in ("target", getattr(_get(role, "role"), "value", None)):
            continue
        name = str(_get(role, "village", "")).strip()
        count = _get(role, kind)
        if name and isinstance(count, int) and not isinstance(count, bool) and count > 0:
            per_location[name] = max(per_location.get(name, 0), count)

    for event in sub_events or ():
        locations = _get(event, "locations", ()) or ()
        event_counts = _positive_counts(_get(event, "casualties"), kind)
        event_total = _get(_get(event, "casualties"), kind)
        if len(locations) == 1 and isinstance(event_total, int) and event_total > 0:
            loc = locations[0]
            if _get(loc, "role", "target") in ("target", getattr(_get(loc, "role"), "value", None)):
                name = str(_get(loc, "village", "")).strip()
                if name:
                    per_location[name] = max(per_location.get(name, 0), event_total)
        for loc in locations:
            if _get(loc, "role", "target") not in ("target", getattr(_get(loc, "role"), "value", None)):
                continue
            name = str(_get(loc, "village", "")).strip()
            count = _get(loc, kind)
            if name and isinstance(count, int) and not isinstance(count, bool) and count > 0:
                per_location[name] = max(per_location.get(name, 0), count)
        # A sub-event total with several targets is an aggregate, not a village row.
        if len(locations) > 1 and event_counts:
            continue
    return list(per_location.items())


def _matched_location_counts(
    match_result: Any,
    kind: str,
) -> dict[int, int]:
    """Return trusted per-location counts keyed by the matched village id.

    Low-confidence and unmatched village resolutions do not establish that a
    count belongs to the resolved database village. They still remain part of
    the bulletin's raw per-location breakdown via ``village_roles``.
    """
    counts: dict[int, int] = {}
    matches = _get(match_result, "village_matches", ()) or ()
    for item in matches:
        if _get(item, "village_role", "target") != "target":
            continue
        if _get(item, "village_match_status") != "matched":
            continue
        village_id = _get(item, "matched_village_id")
        count = _get(item, kind)
        if (
            isinstance(village_id, int)
            and not isinstance(village_id, bool)
            and isinstance(count, int)
            and not isinstance(count, bool)
            and count > 0
        ):
            counts[village_id] = max(counts.get(village_id, 0), count)
    return counts


def _bulletin_total(text: str, casualties: Any, kind: str) -> int | None:
    total = _get(casualties, f"total_{kind}")
    if isinstance(total, int) and not isinstance(total, bool) and total > 0:
        return total
    direct = _get(casualties, kind)
    if isinstance(direct, int) and not isinstance(direct, bool) and direct > 0:
        return direct
    mentions = [
        mention.value
        for mention in find_count_mentions(text)
        if mention.kind == kind and mention.counts_total and mention.value > 0
    ]
    return max(mentions, default=None)


_SAME_DAY_DEATH_ANCHOR = re.compile(
    normalize_casualty_text(r"(?:اليوم|صباح\s+اليوم|اثر\s+الغاره)")
)
_NAMED_VICTIM_DEATH_VERB = re.compile(
    normalize_casualty_text(r"(?:ارتقى|ارتقت|استشهد|استشهدت)")
)


def _current_named_victim_death(text: str) -> bool:
    normalized = normalize_casualty_text(text)
    return bool(
        _NAMED_VICTIM_DEATH_VERB.search(normalized)
        and _SAME_DAY_DEATH_ANCHOR.search(normalized)
        and any(
            mention.kind == DEATHS and mention.value == 1
            for mention in find_count_mentions(text)
        )
    )


def _has_explicit_count(text: str, kind: str) -> bool:
    return any(mention.kind == kind and mention.value > 0 for mention in find_count_mentions(text))


def _is_preliminary(text: str) -> bool:
    cleaned = strip_page_header(text)
    for sentence in sentences(cleaned):
        normalized = normalize_casualty_text(sentence)
        if _FINAL_TOLL.search(normalized):
            continue
        if not (
            has_casualty_wording(sentence, DEATHS)
            or has_casualty_wording(sentence, INJURIES)
        ):
            continue
        if any(pattern.search(normalized) for pattern in _PRELIMINARY_PATTERNS):
            return True
    return False


def _status_for_kind(
    text: str,
    kind: str,
    casualties: Any,
    village_roles: Any,
    sub_events: Any,
    target_location_count: int,
    row_village_id: int | None,
    match_result: Any,
    target_villages: Any = (),
) -> tuple[CasualtyStatusCode, int | None, str | None]:
    if is_obituary(text) and not (kind == DEATHS and _current_named_victim_death(text)):
        return "none_mentioned", None, None

    located = _locations_with_counts(village_roles, sub_events, kind)
    matched_counts = _matched_location_counts(match_result, kind)

    # With one extracted target, root/sub-event casualties belong to that
    # target. Village matching confidence identifies the place; it does not
    # determine ownership of an otherwise unambiguous count.
    if target_location_count == 1:
        if _positive_counts(casualties, kind):
            return "exact", None, _evidence(text, kind)
        # Same precedence as target_location_count_from_extraction: role targets
        # first. The plain village list also names places merely mentioned.
        target_names = _target_location_names(village_roles, sub_events)
        if not target_names:
            target_names = [str(name).strip() for name in target_villages or () if str(name).strip()]
        if not target_names:
            target_names = [name for name, _ in located]
        inferred = infer_count_from_count_words(
            text, kind, target_villages=target_names
        )
        if inferred is not None:
            return "exact", None, _evidence(text, kind)
    if row_village_id is not None and row_village_id in matched_counts:
        return "exact", None, _evidence(text, kind)

    if kind == DEATHS and _current_named_victim_death(text):
        return "exact", None, _evidence(text, kind)

    total = _bulletin_total(text, casualties, kind)
    if located:
        located_sum = sum(count for _, count in located)
        if total is not None and total > located_sum:
            return "aggregate_only", total - located_sum, _evidence(text, kind)
        if row_village_id is None and match_result is None:
            return "exact", None, _evidence(text, kind)
        evidence = _evidence(text, kind)
        if row_village_id is None or row_village_id not in matched_counts:
            note = "Location not tied to a trusted per-location casualty role; not stated for this location."
            evidence = f"{evidence} [{note}]" if evidence else note
        return "none_mentioned", None, evidence

    if target_location_count >= 2 and total is not None:
        all_target_names = [str(name).strip() for name in target_villages or () if str(name).strip()]
        all_target_names.extend(_target_location_names(village_roles, sub_events))
        if (
            not _positive_counts(casualties, kind)
            and (
                _count_is_tied_to_named_location(text, kind, all_target_names)
                or _unlocated_subevent_names_another_place(sub_events, kind)
            )
        ):
            # A count belonging to another named place is not a bulletin total
            # and therefore says nothing about this row.
            return "none_mentioned", None, _evidence(text, kind)
        return "aggregate_only", total, _evidence(text, kind)

    if _has_explicit_count(text, kind) and target_location_count == 1:
        # The text has an exact toll, but the extraction did not persist it.
        return "count_missing", None, _evidence(text, kind)

    if has_explicit_none(text, kind):
        return "explicit_none", None, find_explicit_none(text, kind)

    has_wording = has_casualty_wording(text, kind) or has_vague_quantifier(text, kind)
    if mentions_named_victim(text):
        has_wording = False
    if has_wording:
        return "count_missing", None, _evidence(text, kind)
    return "none_mentioned", None, None


_NAMED_PLACE_ATTRIBUTION = re.compile(
    normalize_casualty_text("(?:من|في) بلدة") + r"\s+[\u0600-\u06ff]"
)


def _unlocated_subevent_names_another_place(sub_events: Any, kind: str) -> bool:
    """Catch a casualty sub-event whose named place was omitted from locations."""
    for event in sub_events or ():
        if not _positive_counts(_get(event, "casualties"), kind):
            continue
        if _get(event, "locations", ()):
            continue
        evidence = str(_get(event, "evidence_span", "") or _get(event, "action_description", ""))
        if _NAMED_PLACE_ATTRIBUTION.search(normalize_casualty_text(evidence)):
            return True
    return False


def _target_location_names(village_roles: Any, sub_events: Any) -> list[str]:
    names: list[str] = []
    for role in village_roles or ():
        value = _get(role, "role", "target")
        if value in ("target", getattr(value, "value", None)):
            name = str(_get(role, "village", "")).strip()
            if name:
                names.append(name)
    for event in sub_events or ():
        for location in _get(event, "locations", ()) or ():
            value = _get(location, "role", "target")
            if value in ("target", getattr(value, "value", None)):
                name = str(_get(location, "village", "")).strip()
                if name:
                    names.append(name)
    return names


def _count_is_tied_to_named_location(
    text: str, kind: str, target_names: list[str]
) -> bool:
    normalized_names = {
        normalize_casualty_text(name) for name in target_names if name.strip()
    }
    for sentence in sentences(strip_page_header(text)):
        if not any(mention.kind == kind for mention in find_count_mentions(sentence)):
            continue
        normalized_sentence = normalize_casualty_text(sentence)
        if any(name and name in normalized_sentence for name in normalized_names):
            return True
    return False


def _evidence(text: str, kind: str) -> str | None:
    cleaned = strip_page_header(text)
    for sentence in sentences(cleaned):
        if has_casualty_wording(sentence, kind) or has_vague_quantifier(sentence, kind):
            return sentence.strip()[:320]
    return None


def derive_casualty_status(
    message_text: str,
    casualties: ExtractionCasualties | dict[str, Any] | None,
    *,
    village_roles: Any = (),
    sub_events: Any = (),
    target_location_count: int,
    row_village_id: int | None = None,
    match_result: Any = None,
    target_villages: Any = (),
) -> CasualtyStatusResult:
    """Derive overall and type-specific statuses from final counts and wording.

    ``remaining_total`` maps ``deaths`` and/or ``injuries`` to counts that a
    bulletin total does not account for after summing known location counts.
    If no location breakdown exists, it contains the full unallocated total.
    """
    cleaned = strip_page_header(message_text)

    deaths_status, deaths_remaining, deaths_evidence = _status_for_kind(
        cleaned, DEATHS, casualties, village_roles, sub_events, target_location_count,
        row_village_id, match_result, target_villages,
    )
    injuries_status, injuries_remaining, injuries_evidence = _status_for_kind(
        cleaned, INJURIES, casualties, village_roles, sub_events, target_location_count,
        row_village_id, match_result, target_villages,
    )
    status = max(
        (deaths_status, injuries_status),
        key=lambda item: _STATUS_PRIORITY[item],
    )
    remaining = {}
    if deaths_status == "aggregate_only" and deaths_remaining is not None:
        remaining[DEATHS] = deaths_remaining
    if injuries_status == "aggregate_only" and injuries_remaining is not None:
        remaining[INJURIES] = injuries_remaining
    evidence = next(
        (
            item
            for item in (deaths_evidence, injuries_evidence)
            if item is not None
        ),
        None,
    )
    return CasualtyStatusResult(
        status=status,
        deaths_status=deaths_status,
        injuries_status=injuries_status,
        is_preliminary=_is_preliminary(cleaned),
        evidence=evidence,
        remaining_total=remaining,
    )


def target_location_count_from_extraction(
    villages: Any,
    village_roles: Any,
    sub_events: Any,
) -> int:
    """Count distinct extracted target locations, including sub-event targets."""
    names: set[str] = set()
    for role in village_roles or ():
        value = _get(role, "role", "target")
        if value not in ("target", getattr(value, "value", None)):
            continue
        name = str(_get(role, "village", "")).strip()
        if name:
            names.add(normalize_casualty_text(name))
    for event in sub_events or ():
        for location in _get(event, "locations", ()) or ():
            value = _get(location, "role", "target")
            if value not in ("target", getattr(value, "value", None)):
                continue
            name = str(_get(location, "village", "")).strip()
            if name:
                names.add(normalize_casualty_text(name))
    if names:
        return len(names)
    return len(
        {
            normalize_casualty_text(str(name).strip())
            for name in villages or ()
            if str(name).strip()
        }
    )


def status_fields(result: CasualtyStatusResult) -> dict[str, Any]:
    """Fields stored on ExtractionResult for backward-compatible JSON persistence."""
    return {
        "casualty_status": result.status,
        "casualty_deaths_status": result.deaths_status,
        "casualty_injuries_status": result.injuries_status,
        "casualty_status_remaining_total": dict(result.remaining_total),
        "casualty_is_preliminary": result.is_preliminary,
        "casualty_status_evidence": result.evidence,
    }


def status_for_incident_row(
    message_text: str,
    extraction: Any,
    row_casualties: Any,
    *,
    target_location_count: int,
    row_village_id: int | None = None,
    match_result: Any = None,
) -> CasualtyStatusResult:
    """Derive status for one incident row from source-to-village attribution.

    Stored row counts are intentionally ignored because legacy materialization
    may have copied bulletin totals onto a location. When another location has
    a complete per-location breakdown and this row does not, ``none_mentioned``
    means "not stated for this location" rather than "no casualties".
    """
    return derive_casualty_status(
        message_text,
        _get(extraction, "casualties"),
        village_roles=_get(extraction, "village_roles", ()),
        sub_events=_get(extraction, "sub_events", ()),
        target_location_count=target_location_count,
        row_village_id=row_village_id,
        match_result=match_result,
        target_villages=_get(extraction, "village", ()),
    )


_MERGE_PRIORITY = {
    "none_mentioned": 0,
    "explicit_none": 1,
    "count_missing": 2,
    "aggregate_only": 2,
    "exact": 3,
}


def merge_casualty_status(
    current_status: str | None,
    current_is_preliminary: bool,
    current_evidence: str | None,
    incoming_status: str | None,
    incoming_is_preliminary: bool,
    incoming_evidence: str | None,
    *,
    incoming_is_newest: bool,
    current_deaths_status: str | None = None,
    incoming_deaths_status: str | None = None,
    current_injuries_status: str | None = None,
    incoming_injuries_status: str | None = None,
    current_remaining_total: dict[str, int] | None = None,
    incoming_remaining_total: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Merge status while preventing downgrades and clearing stale prelim flags."""
    current = current_status if current_status in _MERGE_PRIORITY else "none_mentioned"
    incoming = incoming_status if incoming_status in _MERGE_PRIORITY else "none_mentioned"
    if _MERGE_PRIORITY[incoming] > _MERGE_PRIORITY[current]:
        status, evidence = incoming, incoming_evidence
    elif _MERGE_PRIORITY[incoming] < _MERGE_PRIORITY[current]:
        status, evidence = current, current_evidence
    elif incoming_is_newest:
        status, evidence = incoming, incoming_evidence or current_evidence
    else:
        status, evidence = current, current_evidence
    preliminary = (
        bool(incoming_is_preliminary)
        if incoming_is_newest
        else bool(current_is_preliminary)
    )
    result = {
        "casualty_status": status,
        "casualty_is_preliminary": preliminary,
        "casualty_status_evidence": evidence,
    }
    for field, current_value, incoming_value in (
        ("casualty_deaths_status", current_deaths_status, incoming_deaths_status),
        ("casualty_injuries_status", current_injuries_status, incoming_injuries_status),
    ):
        current_type = current_value if current_value in _MERGE_PRIORITY else None
        incoming_type = incoming_value if incoming_value in _MERGE_PRIORITY else None
        if incoming_type is not None and (
            current_type is None
            or _MERGE_PRIORITY[incoming_type] > _MERGE_PRIORITY[current_type]
            or (
                incoming_is_newest
                and incoming_type in {"explicit_none", "count_missing", "exact"}
            )
        ):
            result[field] = incoming_type
        elif current_type is not None:
            result[field] = current_type
        elif incoming_type is not None:
            result[field] = incoming_type
    if current_remaining_total is not None or incoming_remaining_total is not None:
        result["casualty_status_remaining_total"] = dict(
            incoming_remaining_total
            if incoming_is_newest or current_remaining_total is None
            else current_remaining_total
        )
    return result


_COUNT_FIELDS = {
    "deaths": ("deaths", "total_deaths"),
    "injuries": ("injuries", "total_injuries"),
}


def _is_positive(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def enforce_status_matches_numbers(row: Any) -> bool:
    """Make ``casualty_status`` agree with the row's numbers; True when something changed.

    * a number > 0 never sits next to ``none_mentioned`` (it becomes ``exact``);
    * every number NULL never sits next to ``exact`` (it becomes ``none_mentioned``,
      and the evidence that "proved" it is dropped).

    Other statuses (``count_missing``, ``aggregate_only``, ``explicit_none``) describe
    wording the numbers cannot contradict, so they are left alone.
    """
    changed = False
    kind_status_attr = {
        "deaths": "casualty_deaths_status",
        "injuries": "casualty_injuries_status",
    }
    any_positive = False
    all_null = True
    for kind, fields in _COUNT_FIELDS.items():
        values = [getattr(row, field, None) for field in fields]
        positive = any(_is_positive(value) for value in values)
        any_positive = any_positive or positive
        all_null = all_null and all(value is None for value in values)
        current = getattr(row, kind_status_attr[kind], None)
        if positive and current in (None, "none_mentioned"):
            setattr(row, kind_status_attr[kind], "exact")
            changed = True
        elif all(value is None for value in values) and current == "exact":
            setattr(row, kind_status_attr[kind], "none_mentioned")
            changed = True
    status = getattr(row, "casualty_status", None)
    if any_positive and status in (None, "none_mentioned"):
        row.casualty_status = "exact"
        changed = True
    elif all_null and status == "exact":
        row.casualty_status = "none_mentioned"
        row.casualty_status_evidence = None
        changed = True
    return changed
