from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


LOW_CONFIDENCE_VILLAGE_REVIEW_REASON = (
    "Low-confidence village match requires manual review."
)

LOW_CONFIDENCE_VILLAGE = "low_confidence_village"
CONDITION_REVIEW = "condition_review"
CASUALTY_ALLOCATION = "casualty_allocation"
TIER2_RETRY_CAP = "tier2_retry_cap"
CASUALTY_TRANSITION_CONFLICT = "casualty_transition_conflict"
STORY_REVISION_REVIEW = "story_revision_review"

VAGUE_CASUALTY_REVIEW_REASON = "Casualties are mentioned without an exact number."
AGGREGATE_CASUALTY_REVIEW_REASON = (
    "Aggregate casualty toll across multiple locations has no per-location breakdown."
)
CATEGORY_CASUALTY_REVIEW_REASON = (
    "Category casualties require manual per-village confirmation for a multi-target bulletin"
)


def _get(value: object, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _positive_casualty_total(extraction: object) -> int:
    casualties = _get(extraction, "casualties", {}) or {}
    values = [
        _get(casualties, field)
        for field in (
            "deaths",
            "injuries",
            "total_deaths",
            "total_injuries",
            "male_deaths",
            "male_injuries",
            "female_deaths",
            "female_injuries",
            "children_deaths",
            "children_injuries",
        )
    ]
    return sum(
        value
        for value in values
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
    )


def _has_per_location_casualties(extraction: object) -> bool:
    for role in _get(extraction, "village_roles", ()) or ():
        if _get(role, "role", "target") not in ("target", getattr(_get(role, "role"), "value", None)):
            continue
        if any(
            isinstance(value := _get(role, field), int)
            and not isinstance(value, bool)
            and value > 0
            for field in ("deaths", "injuries")
        ):
            return True
    for event in _get(extraction, "sub_events", ()) or ():
        locations = _get(event, "locations", ()) or ()
        casualties = _get(event, "casualties", {}) or {}
        if len(locations) == 1 and any(
            isinstance(value := _get(casualties, field), int)
            and not isinstance(value, bool)
            and value > 0
            for field in ("deaths", "injuries", "total_deaths", "total_injuries")
        ):
            return True
        for location in locations:
            if any(
                isinstance(value := _get(location, field), int)
                and not isinstance(value, bool)
                and value > 0
                for field in ("deaths", "injuries")
            ):
                return True
    return False


def _claimed_casualty_scope(extraction: object) -> str:
    scope = _get(extraction, "casualty_scope", "unspecified")
    scope = getattr(scope, "value", scope)
    if scope != "unspecified":
        return str(scope)
    old_reason = str(_get(extraction, "casualty_scope_review_reason", "") or "")
    marker = "Unsupported casualty_scope="
    if marker in old_reason:
        return old_reason.split(marker, 1)[1].split(":", 1)[0]
    if _get(extraction, "casualty_status") == "aggregate_only":
        return "bulletin_aggregate"
    return "unspecified"


def casualty_review_reason(
    extraction: object,
    *,
    target_count: int,
    category_casualties_suppressed: bool = False,
) -> str | None:
    """Return a review reason only for product-approved casualty decisions."""
    statuses = (
        _get(extraction, "casualty_status"),
        _get(extraction, "casualty_deaths_status"),
        _get(extraction, "casualty_injuries_status"),
    )
    if "count_missing" in statuses:
        return VAGUE_CASUALTY_REVIEW_REASON
    positive_total = _positive_casualty_total(extraction)
    stored_scope_reason = str(
        _get(extraction, "casualty_scope_review_reason", "") or ""
    )
    if (
        stored_scope_reason.startswith(
            "Split extraction: a bulletin-wide casualty toll"
        )
        and positive_total > 0
        and target_count >= 2
    ):
        return stored_scope_reason
    if category_casualties_suppressed:
        return CATEGORY_CASUALTY_REVIEW_REASON
    if (
        _claimed_casualty_scope(extraction) == "bulletin_aggregate"
        and positive_total > 0
        and target_count >= 2
        and not _has_per_location_casualties(extraction)
    ):
        return AGGREGATE_CASUALTY_REVIEW_REASON
    return None


def _is_weak_village(item: object) -> bool:
    return isinstance(item, dict) and bool(
        item.get("village_review_required")
        or item.get("village_match_status") == "matched_low_confidence"
    )


def unresolved_village_casualty_flags(match: dict | None) -> list[dict]:
    """Quality flags for village mentions that carry casualties but never
    resolved to a village id. These never gate verification (see
    [[data-quality-list]]); they only surface in the data-quality list.
    """
    village_matches = (match or {}).get("village_matches") or []
    flags = []
    for item in village_matches:
        if not isinstance(item, dict):
            continue
        if item.get("matched_village_id") is not None:
            continue
        if item.get("deaths") or item.get("injuries"):
            flags.append(
                {
                    "flag": "unresolved_village_with_casualties",
                    "raw_village_text": item.get("raw_village_text"),
                    "deaths": item.get("deaths"),
                    "injuries": item.get("injuries"),
                }
            )
    return flags


def _condition_signal(
    match: dict,
    village_matches: list,
    village_id: int | None,
) -> str | None:
    """Return the ungrounded-condition review reason for THIS incident's own
    village/sub-event only — never a sibling's, and never the bulletin root
    reason when this incident's own match resolved its condition cleanly.
    """
    if village_id is None:
        candidates = [match.get("condition_review_reason")] + [
            item.get("condition_review_reason")
            for item in village_matches
            if isinstance(item, dict)
        ]
    else:
        own = [
            item
            for item in village_matches
            if isinstance(item, dict) and item.get("matched_village_id") == village_id
        ]
        candidates = (
            [item.get("condition_review_reason") for item in own]
            if own
            else [match.get("condition_review_reason")]
        )
    for reason in candidates:
        reason = str(reason or "")
        if reason.startswith("No usable text-grounded or source-metadata condition"):
            return reason
    return None


def _village_signal(
    match: dict,
    village_matches: list,
    village_id: int | None,
) -> bool:
    """True when the village evidence calls for review of this incident."""
    if village_id is None:
        return bool(match.get("any_village_low_confidence")) or any(
            _is_weak_village(item) for item in village_matches
        )
    own = [
        item
        for item in village_matches
        if isinstance(item, dict) and item.get("matched_village_id") == village_id
    ]
    # A weak mention only counts when no other mention of the same village
    # resolved confidently.
    if own and all(_is_weak_village(item) for item in own):
        return True
    # A village with no id never gets an incident of its own. Casualties on an
    # unresolved village mention are a data-quality problem for that mention,
    # not a reason to flag a sibling incident whose own village resolved
    # confidently — that leaked the review flag across unrelated incidents in
    # the same bulletin. Callers surface the unresolved mention separately
    # (see unresolved_village_casualty_flags).
    return False


def active_non_duplicate_verification_reasons(
    *,
    match_result: dict | None = None,
    extraction_result: dict | None = None,
    tier2_retry_count: int = 0,
    tier2_retry_limit: int | None = None,
    verification_reason: str | None = None,
    low_confidence_village_match: bool = False,
    condition_review_required: bool = False,
    village_id: int | None = None,
) -> frozenset[str]:
    """Derive every active non-duplicate review reason from stored signals.

    ``village_id`` is the incident's own village. When given, the village signal
    is read from that village's matches only, so a sibling incident from the same
    multi-village bulletin is not flagged for another village's weak match. When
    omitted (bulletin-level callers) any weak village counts, as before.
    """
    reasons: set[str] = set()
    match = match_result or {}
    extraction = extraction_result or {}
    village_matches = match.get("village_matches") or []
    if low_confidence_village_match or _village_signal(
        match, village_matches, village_id
    ):
        reasons.add(LOW_CONFIDENCE_VILLAGE)
    if _condition_signal(match, village_matches, village_id):
        reasons.add(CONDITION_REVIEW)
    target_ids = {
        item.get("matched_village_id")
        for item in village_matches
        if isinstance(item, dict)
        and item.get("village_role", "target") == "target"
        and isinstance(item.get("matched_village_id"), int)
    }
    if casualty_review_reason(
        extraction,
        target_count=len(target_ids),
        category_casualties_suppressed=bool(
            extraction.get("category_casualties_suppressed")
        ),
    ):
        reasons.add(CASUALTY_ALLOCATION)
    if tier2_retry_limit is not None and tier2_retry_count >= tier2_retry_limit:
        reasons.add(TIER2_RETRY_CAP)

    stored = (verification_reason or "").strip().casefold()
    if stored and not stored.startswith(("possible duplicate", "possible cross-source duplicate")):
        if stored == LOW_CONFIDENCE_VILLAGE_REVIEW_REASON.casefold():
            reasons.add(LOW_CONFIDENCE_VILLAGE)
        elif stored.startswith("no usable text-grounded or source-metadata condition"):
            reasons.add(CONDITION_REVIEW)
        elif stored.startswith((
            "low-confidence condition text match",
            "source metadata fallback used",
        )):
            pass
        elif stored.startswith(("category casualties", "unsupported casualty_scope")):
            reasons.add(CASUALTY_ALLOCATION)
        elif stored.startswith("tier 2 detail extraction failed"):
            reasons.add(TIER2_RETRY_CAP)
        elif "casualty count conflict" in stored or "casualty transition" in stored:
            reasons.add(CASUALTY_TRANSITION_CONFLICT)
        elif "story revision" in stored:
            reasons.add(STORY_REVISION_REVIEW)
        else:
            # Unknown stored non-duplicate reasons remain review-worthy rather
            # than being erased by a duplicate decision.
            reasons.add("stored_review_reason")
    return frozenset(reasons)


def _verification_reason(
    match_result: dict | None,
    *,
    duplicate_flag: bool = False,
    duplicate_level: str | None = None,
    duplicate_similarity_score: float | None = None,
    insufficient_score: bool = False,
    low_confidence_village_match: bool = False,
    condition_review_reason: str | None = None,
    hard_reasons: tuple[str, ...] = (),
) -> str | None:
    """Return all hard reasons first, followed by informational hints."""
    reasons: list[str] = []
    if duplicate_flag:
        if duplicate_level is not None and duplicate_similarity_score is not None:
            reasons.append(
                "Possible duplicate of an existing incident "
                f"(similarity {duplicate_level}, score {duplicate_similarity_score:.2f})."
            )
        else:
            reasons.append(
                "Possible duplicate of an existing incident — flagged during "
                "fast-path matching."
            )
    elif insufficient_score:
        reasons.append(
            "Possible duplicate of an existing incident — flagged during "
            "fast-path matching."
        )
    reasons.extend(reason for reason in hard_reasons if reason)
    if low_confidence_village_match:
        reasons.append(LOW_CONFIDENCE_VILLAGE_REVIEW_REASON)
    if condition_review_reason:
        reasons.append(condition_review_reason)
    return "; ".join(dict.fromkeys(reasons)) or None


# --- New verification policy (Phase 4, decided 2026-10-05) -----------------
#
# Only two things may put an incident in the human review queue:
#   rule 1 — casualty attribution (handled by casualty_review_reason above)
#   rule 2 — a likely duplicate that cannot be auto-linked safely
# Rule 3 (governance safeguards: a verified incident changed by a pipeline
# write, a casualty-count conflict/transition detected on merge, admin
# restore from rejected) is implemented at the call sites that already own
# that state and is passed straight through as `governance_hard_reasons`.
# Everything else this module used to treat as a review reason — low-
# confidence village, an ungrounded condition, the tier-2 retry cap,
# multi_village_no_subevents, flare/strike wording — becomes a quality flag
# for the developer-facing data-quality list instead (see
# `app/core/llm_knowledge/CHANGELOG.md`).

DuplicateOutcome = Literal["none", "review", "auto_link"]
ReviewRule = Literal["duplicate", "casualty_attribution", "governance"]


def review_quality_payload(
    *,
    review_rule: ReviewRule | None,
    review_message: str | None,
    review_data: dict[str, Any] | None = None,
    quality_flags: list[dict] | None = None,
) -> dict[str, Any] | list[dict] | None:
    flags = quality_flags or []
    if review_rule is None and not flags:
        return None
    payload: dict[str, Any] = {"quality_flags": flags}
    if review_rule is not None and review_message:
        payload["review"] = {
            "rule": review_rule,
            "message": review_message,
            "data": review_data or {},
        }
    return payload


def extract_quality_flags(value: Any) -> list[dict]:
    if isinstance(value, dict):
        flags = value.get("quality_flags")
        return flags if isinstance(flags, list) else []
    return value if isinstance(value, list) else []


def extract_review_payload(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    review = value.get("review")
    return review if isinstance(review, dict) else None


def decide_duplicate_outcome(
    similarity_score: float | None,
    *,
    same_village: bool = False,
    same_condition: bool = False,
    same_casualties: bool = False,
    event_gap_hours: float | None = None,
    review_threshold: float | None = None,
    autolink_threshold: float | None = None,
    autolink_max_gap_hours: float | None = None,
) -> DuplicateOutcome:
    """Classify one duplicate candidate's similarity score.

    ``review_threshold``/``autolink_threshold``/``autolink_max_gap_hours``
    default to ``settings.duplicate_review_threshold`` /
    ``duplicate_autolink_threshold`` / ``duplicate_autolink_max_event_gap_hours``
    so the bands stay env/settings-driven, never hardcoded by a caller.
    """
    if similarity_score is None:
        return "none"
    if review_threshold is None or autolink_threshold is None or autolink_max_gap_hours is None:
        from app.core.config import settings as _settings

        review_threshold = (
            review_threshold
            if review_threshold is not None
            else _settings.duplicate_review_threshold
        )
        autolink_threshold = (
            autolink_threshold
            if autolink_threshold is not None
            else _settings.duplicate_autolink_threshold
        )
        autolink_max_gap_hours = (
            autolink_max_gap_hours
            if autolink_max_gap_hours is not None
            else _settings.duplicate_autolink_max_event_gap_hours
        )
    if similarity_score >= autolink_threshold:
        safe_gap = event_gap_hours is not None and event_gap_hours <= autolink_max_gap_hours
        if same_village and same_condition and same_casualties and safe_gap:
            return "auto_link"
        return "review"
    if similarity_score >= review_threshold:
        return "review"
    return "none"


@dataclass(frozen=True)
class VerificationSignals:
    """Everything `decide_verification` needs, gathered by the caller."""

    match_result: dict | None = None
    extraction_result: dict | None = None
    village_id: int | None = None
    tier2_retry_count: int = 0
    tier2_retry_limit: int | None = None
    # Rule 2 inputs — the strongest duplicate candidate found by the existing
    # dedup services (fast-path, full materialization, or the tier-2 backstop).
    duplicate_similarity_score: float | None = None
    duplicate_candidate_id: Any = None
    duplicate_same_village: bool = False
    duplicate_same_condition: bool = False
    duplicate_same_casualties: bool = False
    duplicate_event_gap_hours: float | None = None
    # Rule 3 — pre-formed governance-safeguard reason strings from the call
    # site that owns that state (see module docstring above). Passed through
    # verbatim; never re-derived here.
    governance_hard_reasons: tuple[str, ...] = ()
    # Pipeline-accuracy signals that must NOT gate review under the new
    # policy — captured as quality flags only.
    multi_village_no_subevents: bool = False
    flare_wording_detail: str | None = None
    # Some call sites (the fast materialization path) only have the already
    # product-approved casualty_review_reason string on hand, not the full
    # ExtractionResult dict `casualty_review_reason` needs. When set, this
    # short-circuits rule 1's own recomputation.
    precomputed_casualty_reason: str | None = None
    # Likewise: some callers (e.g. the plain-"between X and Y" village
    # collapse) already know their own match is low-confidence from a
    # locally-rewritten village_match that isn't reflected in the raw
    # message's stored match_result. Forces the quality flag either way.
    low_confidence_village_override: bool = False


def decide_verification(
    incident: object | None,
    signals: VerificationSignals,
) -> tuple[str, list[str], list[dict], dict[str, Any] | list[dict] | None]:
    """The single gate for `needs_verification` (rules 1-3 above).

    Returns ``(status, reasons, quality_flags)``. ``status`` is
    ``"needs_verification"`` or ``"auto_processed"``; ``reasons`` is the
    ordered, de-duplicated list of display strings for
    ``incident.verification_reason``; ``quality_flags`` is the list of
    structured flags for the data-quality list (Part D) — never stored on
    ``verification_reason`` and never used to decide ``status``.
    """
    match = signals.match_result or {}
    extraction = signals.extraction_result or {}
    village_matches = match.get("village_matches") or []
    village_id = (
        signals.village_id
        if incident is None
        else getattr(incident, "village_id", signals.village_id)
    )

    reasons: list[str] = list(signals.governance_hard_reasons)

    target_ids = {
        item.get("matched_village_id")
        for item in village_matches
        if isinstance(item, dict)
        and item.get("village_role", "target") == "target"
        and isinstance(item.get("matched_village_id"), int)
    }
    casualty_reason = signals.precomputed_casualty_reason or casualty_review_reason(
        extraction,
        target_count=len(target_ids),
        category_casualties_suppressed=bool(
            extraction.get("category_casualties_suppressed")
        ),
    )
    if casualty_reason:
        reasons.append(casualty_reason)

    duplicate_outcome = decide_duplicate_outcome(
        signals.duplicate_similarity_score,
        same_village=signals.duplicate_same_village,
        same_condition=signals.duplicate_same_condition,
        same_casualties=signals.duplicate_same_casualties,
        event_gap_hours=signals.duplicate_event_gap_hours,
    )
    if duplicate_outcome == "review":
        score = signals.duplicate_similarity_score or 0.0
        reasons.append(
            f"{round(score * 100)}% similar to an existing incident from "
            "another source — confirm whether this is a duplicate."
        )

    quality_flags: list[dict] = []
    if _condition_signal(match, village_matches, village_id):
        quality_flags.append({"flag": "unresolved_condition"})
    if (
        signals.low_confidence_village_override
        or _village_signal(match, village_matches, village_id)
        or bool(match.get("any_village_low_confidence"))
    ):
        quality_flags.append({"flag": "low_confidence_village"})
    quality_flags.extend(unresolved_village_casualty_flags(match))
    if (
        signals.tier2_retry_limit is not None
        and signals.tier2_retry_count >= signals.tier2_retry_limit
    ):
        quality_flags.append(
            {"flag": "tier2_retry_cap", "retry_count": signals.tier2_retry_count}
        )
    if signals.multi_village_no_subevents:
        quality_flags.append({"flag": "multi_village_no_subevents"})
    if signals.flare_wording_detail:
        quality_flags.append(
            {"flag": "flare_wording", "detail": signals.flare_wording_detail}
        )

    selected_reason = next(iter(dict.fromkeys(reasons)), None)
    status = "needs_verification" if selected_reason else "auto_processed"
    review_rule: ReviewRule | None = None
    if selected_reason:
        lowered = selected_reason.casefold()
        if "similar to an existing incident" in lowered or "possible duplicate" in lowered:
            review_rule = "duplicate"
        elif selected_reason in signals.governance_hard_reasons:
            review_rule = "governance"
        else:
            review_rule = "casualty_attribution"
    structured_payload = review_quality_payload(
        review_rule=review_rule,
        review_message=selected_reason,
        review_data={
            "candidate_id": (
                str(signals.duplicate_candidate_id)
                if signals.duplicate_candidate_id is not None
                else None
            ),
            "similarity": signals.duplicate_similarity_score,
        }
        if review_rule == "duplicate"
        else {},
        quality_flags=quality_flags,
    )
    return status, ([selected_reason] if selected_reason else []), quality_flags, structured_payload
