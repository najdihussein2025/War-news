"""Recompute machine-owned incident verification state.

Dry-run is the default. Pass ``--apply`` to persist in batches.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.news.models import Incident, IncidentUpdate, RawMessage, UpdateAction
from app.news.repositories.condition_repository import ConditionRepository
from app.news.repositories.village_repository import VillageRepository
from app.news.services.matching.matching_service import MatchingService
from app.llm.dtos import ExtractionResult
from app.llm.services.action_finalization import FLARE_GUARD_REVIEW_REASON
from app.llm.services.ollama_extraction_service import (
    MULTI_VILLAGE_NO_SUBEVENTS_REVIEW_REASON as MULTI_VILLAGE_NO_SUBEVENTS_MARKER,
)
from app.news.services.materialization.verification_signals import (
    VerificationSignals,
    decide_verification,
)


@dataclass(frozen=True)
class Recomputed:
    status: str
    reason: str | None
    condition_id: int | None
    quality_flags: list[dict]
    quality_payload: dict | list[dict] | None


def _reason_bucket(reason: str | None) -> str:
    value = (reason or "").strip()
    if not value:
        return "[NULL/empty]"
    if value.startswith("Low-confidence condition text match"):
        return "Low-confidence condition"
    if value.startswith("Low-confidence village match"):
        return "Low-confidence village"
    if value.startswith("Unsupported casualty_scope"):
        return "Unsupported casualty scope"
    if value.startswith("Category casualties"):
        return "Category casualty suppression"
    if value.startswith("No usable text-grounded"):
        return "No usable condition"
    if value.startswith("Possible cross-source duplicate"):
        return "Cross-source duplicate"
    return value


def _rule_bucket(reason: str | None) -> str:
    """Classify an active review reason into rule 1/2/3 for the Part E report."""
    value = (reason or "").strip().casefold()
    if not value:
        return "[none]"
    if (
        "casualty count conflict" in value
        or "casualty transition" in value
        or "unconfirmed story revision" in value
        or "pipeline merged raw message" in value
        or "story revision from raw message" in value
    ):
        return "rule 3: governance safeguard"
    if "similar to an existing incident" in value or "possible duplicate" in value or "possible cross-source duplicate" in value:
        return "rule 2: likely duplicate"
    return "rule 1: casualty attribution"


def _latest_status_change_is_manual(db, incident_id) -> bool:
    update = db.scalar(
        select(IncidentUpdate)
        .where(
            IncidentUpdate.incident_id == incident_id,
            IncidentUpdate.action == UpdateAction.status_change,
            IncidentUpdate.new_values.has_key("verification_status"),  # type: ignore[attr-defined]
        )
        .order_by(IncidentUpdate.created_at.desc(), IncidentUpdate.id.desc())
        .limit(1)
    )
    return update is not None and update.performed_by is not None


def _incident_match(match: dict[str, Any], village_id: int | None) -> dict[str, Any] | None:
    candidates = match.get("village_matches") or []
    return next(
        (
            item
            for item in candidates
            if isinstance(item, dict)
            and item.get("matched_village_id") == village_id
            and item.get("village_role", "target") == "target"
        ),
        None,
    )


def _rerun_condition(
    matcher: MatchingService,
    raw: RawMessage,
    incident: Incident,
) -> tuple[int | None, str | None]:
    match = dict(raw.match_result or {})
    own = _incident_match(match, incident.village_id)
    text = (
        (own or {}).get("raw_condition_text")
        or match.get("raw_condition_text")
        or (raw.extraction_result or {}).get("action_description")
    )
    resolution = matcher._resolve_condition(
        text,
        source_hint=match.get("source_condition_text"),
        action_source=match.get("condition_action_source"),
    )
    classified = resolution.match
    condition_id = classified.matched_id
    condition_hint = resolution.review_reason

    target = own if own is not None else match
    target["matched_condition_id"] = condition_id
    target["condition_confidence"] = classified.confidence
    target["condition_match_status"] = classified.status.value
    target["condition_review_required"] = resolution.review_required
    target["condition_review_reason"] = condition_hint
    target["condition_action_source"] = resolution.action_source
    if own is not None and match.get("raw_condition_text") == text:
        for key in (
            "matched_condition_id",
            "condition_confidence",
            "condition_match_status",
            "condition_review_required",
            "condition_review_reason",
            "condition_action_source",
        ):
            match[key] = target[key]
    raw.match_result = match
    return condition_id, condition_hint


def _rerun_match(
    matcher: MatchingService,
    raw: RawMessage,
) -> dict[str, Any]:
    extraction = ExtractionResult.model_validate(raw.extraction_result or {})
    result = matcher.match(
        extraction,
        cnrs_classification=getattr(raw, "cnrs_classification", None),
    )
    match = result.model_dump(mode="json")
    raw.match_result = match
    return match


def _preserved_governance_reasons(reason: str | None) -> list[str]:
    """Reasons this script preserves verbatim rather than recomputing.

    Rule 3 (governance safeguards) — casualty-count conflicts/transitions on
    merge, an unconfirmed heuristic story revision, a pipeline write that
    changed a verified incident — always survives, since those safeguards
    own their own state and this script doesn't re-derive them.

    "Possible cross-source duplicate" (SegmentReviewDedupService) also
    survives: it's a rule 2 (likely duplicate) decision this script cannot
    recompute, since doing so would require re-running segment-level dedup,
    not just village/condition matching. The village-level dedup duplicate
    text (plain "possible duplicate") is NOT preserved — decide_verification
    recomputes that one fresh from the stored duplicate_similarity_score.

    Everything else (flare wording, multi_village_no_subevents, tier-2 retry
    cap, low-confidence village/condition) is dropped here and recomputed as
    a quality flag instead, never carried over as review-reason text.
    """
    value = (reason or "").strip()
    lower = value.casefold()
    if not value:
        return []
    preserved_markers = (
        "casualty count conflict",
        "casualty transition",
        "unconfirmed story revision",
        "pipeline merged raw message",
        "story revision from raw message",
    )
    return [value] if any(marker in lower for marker in preserved_markers) else []


def recompute(
    incident: Incident,
    raw: RawMessage,
    matcher: MatchingService,
) -> Recomputed:
    match = _rerun_match(matcher, raw)
    own = _incident_match(match, incident.village_id) or {}
    condition_id = own.get("matched_condition_id") or match.get("matched_condition_id")
    extraction = dict(raw.extraction_result or {})

    governance_hard_reasons = _preserved_governance_reasons(incident.verification_reason)
    # `extraction.review_reason` is a multiplexed field: it can hold the rule
    # 1 casualty text (decide_verification recomputes that fresh from the
    # same extraction dict, so it's not re-added here), the flare/strike
    # wording guard, or the multi_village_no_subevents marker. Only the
    # latter two are extracted here, and only as quality flags — neither is
    # a rule 1/2/3 review reason under the new policy.
    extraction_review_reason = str(extraction.get("review_reason") or "")
    flare_wording_detail = (
        extraction_review_reason if FLARE_GUARD_REVIEW_REASON in extraction_review_reason else None
    )
    multi_village_no_subevents = (
        MULTI_VILLAGE_NO_SUBEVENTS_MARKER in extraction_review_reason
    )

    # The candidate this incident was flagged as a possible duplicate of is
    # not re-queried here (this script only reruns village/condition
    # matching, not dedup search) — default same_condition/same_casualties
    # to False so a recompute never silently auto-links; it only ever
    # narrows the review band down from the stored duplicate_flag.
    status, reasons, quality_flags, quality_payload = decide_verification(
        incident,
        VerificationSignals(
            match_result=match,
            extraction_result=extraction,
            village_id=incident.village_id,
            tier2_retry_count=raw.tier2_retry_count or 0,
            tier2_retry_limit=settings.extraction_max_retries,
            governance_hard_reasons=tuple(governance_hard_reasons),
            flare_wording_detail=flare_wording_detail,
            multi_village_no_subevents=multi_village_no_subevents,
            duplicate_similarity_score=(
                incident.duplicate_similarity_score
                if incident.duplicate_flag
                else None
            ),
            duplicate_same_village=True,
        ),
    )
    reason = "; ".join(reasons) or None
    return Recomputed(
        status=status,
        reason=reason,
        condition_id=condition_id or incident.condition_id,
        quality_flags=quality_flags,
        quality_payload=quality_payload,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")

    db = SessionLocal()
    processed = succeeded = failed = skipped = 0
    transitions: Counter[tuple[str, str, str]] = Counter()
    samples: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    rule_counts: Counter[str] = Counter()
    quality_flag_counts: Counter[str] = Counter()
    matcher = MatchingService(VillageRepository(db), ConditionRepository(db))
    try:
        incidents = list(
            db.scalars(
                select(Incident)
                .where(
                    Incident.is_deleted.is_(False),
                    Incident.verification_status == "needs_verification",
                )
                .order_by(Incident.created_at.asc(), Incident.id.asc())
            ).all()
        )
        for incident in incidents:
            processed += 1
            if processed == 1 or processed % 100 == 0:
                print(f"progress processed={processed}/{len(incidents)}", flush=True)
            try:
                if incident.verified_by_user_id is not None or _latest_status_change_is_manual(
                    db, incident.id
                ):
                    skipped += 1
                    continue
                raw = db.get(RawMessage, incident.raw_message_id)
                if raw is None:
                    failed += 1
                    continue
                outcome = recompute(incident, raw, matcher)
                old_bucket = _reason_bucket(incident.verification_reason)
                new_bucket = _reason_bucket(outcome.reason)
                key = (old_bucket, outcome.status, new_bucket)
                transitions[key] += 1
                if len(samples[key]) < 10:
                    samples[key].append(str(incident.id))
                if outcome.status == "needs_verification":
                    rule_counts[_rule_bucket(outcome.reason)] += 1
                for flag in outcome.quality_flags:
                    quality_flag_counts[str(flag.get("flag"))] += 1
                if args.apply:
                    incident.verification_status = outcome.status
                    incident.verification_reason = outcome.reason
                    incident.condition_id = outcome.condition_id
                    incident.quality_flags = outcome.quality_payload
                    db.add(raw)
                    db.add(incident)
                    if succeeded and succeeded % args.batch_size == 0:
                        db.commit()
                else:
                    db.rollback()
                succeeded += 1
            except Exception as exc:  # keep batch accounting explicit
                db.rollback()
                failed += 1
                print(f"ERROR incident={incident.id}: {exc}")
        if args.apply:
            db.commit()

        print("| Old reason bucket | New status | New reason bucket | Count | Samples |")
        print("|---|---|---|---:|---|")
        for key, count in sorted(transitions.items(), key=lambda item: (-item[1], item[0])):
            print(
                f"| {key[0]} | {key[1]} | {key[2]} | {count} | "
                f"{', '.join(samples[key])} |"
            )

        print("\n## Projected review queue, by rule")
        print("| Rule | Incidents |")
        print("|---|---:|")
        for rule, count in sorted(rule_counts.items(), key=lambda item: -item[1]):
            print(f"| {rule} | {count} |")

        print("\n## Quality flags (developer-facing, not the review queue)")
        print("| Flag | Incidents |")
        print("|---|---:|")
        for flag, count in sorted(quality_flag_counts.items(), key=lambda item: -item[1]):
            print(f"| {flag} | {count} |")

        mode = "apply" if args.apply else "dry-run"
        print(
            f"mode={mode} processed={processed} succeeded={succeeded} "
            f"failed={failed} skipped={skipped}"
        )
        return 1 if failed else 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
