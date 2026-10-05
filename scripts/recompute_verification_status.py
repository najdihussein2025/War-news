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
from app.news.services.materialization.verification_signals import (
    CONDITION_REVIEW,
    LOW_CONFIDENCE_VILLAGE,
    LOW_CONFIDENCE_VILLAGE_REVIEW_REASON,
    TIER2_RETRY_CAP,
    active_non_duplicate_verification_reasons,
    casualty_review_reason,
    _verification_reason,
)


@dataclass(frozen=True)
class Recomputed:
    status: str
    reason: str | None
    condition_id: int | None


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


def _preserved_hard_reasons(reason: str | None) -> list[str]:
    value = (reason or "").strip()
    lower = value.casefold()
    if not value:
        return []
    hard_markers = (
        "possible cross-source duplicate",
        "possible duplicate",
        "flare wording",
        "multi_village_no_subevents",
        "casualty count conflict",
        "casualty transition",
        "unconfirmed story revision",
        "pipeline merged raw message",
        "story revision from raw message",
        "tier 2 detail extraction failed",
    )
    return [value] if any(marker in lower for marker in hard_markers) else []


def recompute(
    incident: Incident,
    raw: RawMessage,
    matcher: MatchingService,
) -> Recomputed:
    match = _rerun_match(matcher, raw)
    own = _incident_match(match, incident.village_id) or {}
    condition_id = own.get("matched_condition_id") or match.get("matched_condition_id")
    # Scoped to this incident's own village/sub-event match only — never a
    # sibling's or the bulletin-root reason, which would leak onto an
    # incident whose own condition resolved cleanly (Bug 1).
    condition_hint = own.get("condition_review_reason")
    match = dict(raw.match_result or {})
    extraction = dict(raw.extraction_result or {})
    own = _incident_match(match, incident.village_id) or {}
    target_ids = {
        item.get("matched_village_id")
        for item in match.get("village_matches") or []
        if isinstance(item, dict)
        and item.get("village_role", "target") == "target"
        and isinstance(item.get("matched_village_id"), int)
    }

    hard_reasons = _preserved_hard_reasons(incident.verification_reason)
    casualty_reason = casualty_review_reason(
        extraction,
        target_count=len(target_ids),
        category_casualties_suppressed=bool(
            extraction.get("category_casualties_suppressed")
        ),
    )
    if casualty_reason:
        hard_reasons.append(casualty_reason)
    if extraction.get("needs_review") and extraction.get("review_reason"):
        hard_reasons.append(str(extraction["review_reason"]))
    if (raw.tier2_retry_count or 0) >= settings.extraction_max_retries:
        hard_reasons.append(
            f"Tier 2 detail extraction failed after {raw.tier2_retry_count} retries"
        )

    active = active_non_duplicate_verification_reasons(
        match_result=match,
        extraction_result=extraction,
        tier2_retry_count=raw.tier2_retry_count or 0,
        tier2_retry_limit=settings.extraction_max_retries,
        verification_reason=None,
        village_id=incident.village_id,
    )
    village_hard = LOW_CONFIDENCE_VILLAGE in active
    unresolved_condition = CONDITION_REVIEW in active or condition_id in (None, 87)
    if unresolved_condition:
        hard_reasons.append(
            condition_hint
            or "No usable text-grounded or source-metadata condition candidate."
        )
    if TIER2_RETRY_CAP in active and not any(
        reason.startswith("Tier 2 detail extraction failed") for reason in hard_reasons
    ):
        hard_reasons.append("Tier 2 detail extraction failed after retry cap")

    reason = _verification_reason(
        match,
        duplicate_flag=bool(incident.duplicate_flag),
        duplicate_level=incident.duplicate_level,
        duplicate_similarity_score=incident.duplicate_similarity_score,
        low_confidence_village_match=village_hard,
        condition_review_reason=(condition_hint if not unresolved_condition else None),
        hard_reasons=tuple(hard_reasons),
    )
    needs_review = bool(
        incident.duplicate_flag or village_hard or hard_reasons or unresolved_condition
    )
    return Recomputed(
        status="needs_verification" if needs_review else "auto_processed",
        reason=reason,
        condition_id=condition_id or incident.condition_id,
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
                if args.apply:
                    incident.verification_status = outcome.status
                    incident.verification_reason = outcome.reason
                    incident.condition_id = outcome.condition_id
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
