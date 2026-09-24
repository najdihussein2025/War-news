from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select, text

from app.core.database import SessionLocal
from app.llm.dtos import ExtractionResult
from app.llm.services.cnrs_extraction_fallback import trusted_cnrs_action
from app.news.dtos import MatchResultDTO, MatchResultStatus
from app.news.models import Condition, MessageStatus, RawMessage
from app.news.repositories.condition_repository import ConditionRepository
from app.news.repositories.village_repository import VillageRepository
from app.news.services.matching.condition_evidence_override import (
    apply_condition_evidence_override,
)
from app.news.services.matching.matching_service import MatchingService


ELIGIBLE_STATUSES = (
    MessageStatus.parsed,
    MessageStatus.materialized,
    MessageStatus.duplicate,
)


@dataclass(frozen=True)
class IncidentConditionPlan:
    incident_id: str
    raw_message_id: int
    old_condition_id: int | None
    new_condition_id: int | None
    old_condition: str | None
    new_condition: str | None
    review_required: bool
    review_reason: str | None

    @property
    def changes_condition(self) -> bool:
        return self.old_condition_id != self.new_condition_id


def _condition_labels(db) -> dict[int, str]:
    return {
        condition.id: condition.action_en
        for condition in db.scalars(select(Condition)).all()
    }


def _source_subtype(classification: dict[str, Any] | None) -> str | None:
    subtype = str((classification or {}).get("event_subtype") or "").strip().lower()
    return subtype or None


def _reconciled_extraction(message: RawMessage) -> ExtractionResult:
    extraction = ExtractionResult.model_validate(message.extraction_result)
    raw_text = message.raw_text or ""
    source_hint = trusted_cnrs_action(message.cnrs_classification, raw_text)
    text_action = apply_condition_evidence_override(
        raw_text,
        extraction.action_description,
    )
    action_source = (
        "llm_text"
        if text_action
        else "cnrs_subtype_fallback"
        if source_hint
        else extraction.action_source
    )
    return extraction.model_copy(
        update={
            "action_description": text_action or source_hint,
            "action_source": action_source,
            "source_event_subtype": _source_subtype(message.cnrs_classification),
            "source_action_hint": source_hint,
        }
    )


def _condition_for_incident(
    village_id: int | None,
    result: MatchResultDTO,
) -> tuple[int | None, bool, str | None]:
    matches = result.village_matches or []
    if village_id is not None:
        for match in matches:
            if match.matched_village_id == village_id:
                return (
                    match.matched_condition_id,
                    bool(match.condition_review_required),
                    match.condition_review_reason,
                )
    return (
        result.matched_condition_id,
        bool(result.condition_review_required),
        result.condition_review_reason,
    )


def _plan_message(
    db,
    message: RawMessage,
    matcher: MatchingService,
    labels: dict[int, str],
) -> tuple[MatchResultDTO, list[IncidentConditionPlan]]:
    extraction = _reconciled_extraction(message)
    result = matcher.match(
        extraction,
        cnrs_classification=message.cnrs_classification,
    )
    incidents = db.execute(
        text(
            """
            SELECT id, village_id, condition_id
            FROM incidents
            WHERE raw_message_id = :raw_message_id
              AND is_deleted IS FALSE
            ORDER BY created_at ASC
            """
        ),
        {"raw_message_id": message.id},
    ).mappings().all()
    plans: list[IncidentConditionPlan] = []
    for incident in incidents:
        new_condition_id, review_required, review_reason = _condition_for_incident(
            incident["village_id"],
            result,
        )
        plans.append(
            IncidentConditionPlan(
                incident_id=str(incident["id"]),
                raw_message_id=message.id,
                old_condition_id=incident["condition_id"],
                new_condition_id=new_condition_id,
                old_condition=(
                    labels.get(incident["condition_id"])
                    if incident["condition_id"] is not None
                    else None
                ),
                new_condition=(
                    labels.get(new_condition_id)
                    if new_condition_id is not None
                    else None
                ),
                review_required=review_required,
                review_reason=review_reason,
            )
        )
    return result, plans


def _eligible_query(args: argparse.Namespace):
    query = (
        select(RawMessage)
        .where(
            RawMessage.extraction_result.is_not(None),
            RawMessage.status.in_(ELIGIBLE_STATUSES),
        )
        .order_by(RawMessage.id.asc())
    )
    if args.raw_id:
        query = query.where(RawMessage.id.in_(args.raw_id))
    if args.since_id is not None:
        query = query.where(RawMessage.id >= args.since_id)
    if args.limit is not None:
        query = query.limit(args.limit)
    return query


def run(args: argparse.Namespace) -> int:
    with SessionLocal() as db:
        matcher = MatchingService(
            VillageRepository(db),
            ConditionRepository(db),
        )
        labels = _condition_labels(db)
        messages = list(db.scalars(_eligible_query(args)).all())
        counters: Counter[str] = Counter()
        examples: list[IncidentConditionPlan] = []

        for message in messages:
            result, plans = _plan_message(db, message, matcher, labels)
            counters["raw_messages_scanned"] += 1
            if message.match_result != result.model_dump(mode="json"):
                counters["raw_match_results_changed"] += 1
                if args.apply:
                    message.match_result = result.model_dump(mode="json")
                    message.matched_at = datetime.now().astimezone()
                    db.add(message)

            extraction = _reconciled_extraction(message)
            if message.extraction_result != extraction.model_dump(mode="json"):
                counters["extraction_metadata_changed"] += 1
                if args.apply:
                    message.extraction_result = extraction.model_dump(mode="json")
                    db.add(message)

            for plan in plans:
                counters["incidents_scanned"] += 1
                if plan.changes_condition and plan.new_condition_id is None:
                    counters["incident_conditions_need_unclassified_condition"] += 1
                    if len(examples) < args.examples:
                        examples.append(plan)
                elif plan.changes_condition:
                    counters["incident_conditions_changed"] += 1
                    if len(examples) < args.examples:
                        examples.append(plan)
                    if args.apply and plan.new_condition_id is not None:
                        values: dict[str, Any] = {
                            "incident_id": plan.incident_id,
                            "condition_id": plan.new_condition_id,
                        }
                        review_sql = ""
                        if plan.review_required:
                            review_sql = (
                                ", verification_status = 'needs_verification', "
                                "verification_reason = :verification_reason"
                            )
                            values["verification_reason"] = plan.review_reason
                        db.execute(
                            text(
                                "UPDATE incidents "
                                "SET condition_id = :condition_id"
                                f"{review_sql} "
                                "WHERE id = :incident_id"
                            ),
                            values,
                        )
                elif plan.review_required:
                    counters["incident_review_only"] += 1
                    if args.apply:
                        db.execute(
                            text(
                                "UPDATE incidents "
                                "SET verification_status = 'needs_verification', "
                                "verification_reason = :verification_reason "
                                "WHERE id = :incident_id"
                            ),
                            {
                                "incident_id": plan.incident_id,
                                "verification_reason": plan.review_reason,
                            },
                        )

        if args.apply:
            db.commit()
        else:
            db.rollback()

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"condition reconciliation backfill: {mode}")
    for key in sorted(counters):
        print(f"{key}={counters[key]}")
    if examples:
        print("\nexamples:")
        for plan in examples:
            print(
                f"raw={plan.raw_message_id} incident={plan.incident_id} "
                f"{plan.old_condition_id}:{plan.old_condition} -> "
                f"{plan.new_condition_id}:{plan.new_condition} "
                f"review={plan.review_required} reason={plan.review_reason!r}"
            )
    if not args.apply:
        print("\nNo rows were changed. Re-run with --apply to write updates.")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Replay condition reconciliation for existing raw messages and linked incidents."
        )
    )
    parser.add_argument("--apply", action="store_true", help="write changes")
    parser.add_argument("--limit", type=int, help="maximum raw messages to scan")
    parser.add_argument("--since-id", type=int, help="only scan raw_messages.id >= this")
    parser.add_argument(
        "--raw-id",
        type=int,
        action="append",
        default=[],
        help="specific raw_message id to scan; may be repeated",
    )
    parser.add_argument("--examples", type=int, default=20)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
