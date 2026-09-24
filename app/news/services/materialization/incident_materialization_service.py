from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.text_normalization import normalize_arabic_text
from app.core.text_sanitizer import strip_emoji_and_pictographs
from app.llm.dtos import (
    CasualtyScope,
    ExtractionCasualties,
    ExtractionResult,
    ExtractionSubEvent,
    StoryRelationship,
    VillageRole,
)
from app.news.interfaces import DedupMatchingInterface
from app.news.models import (
    Incident,
    IncidentDetail,
    IncidentUpdate,
    MatchStatus,
    MessageStatus,
    RawMessage,
    UpdateAction,
)
from app.news.repositories.incident_repository import IncidentRepository
from app.news.repositories.emergency_organization_repository import (
    EmergencyOrganizationRepository,
)
from app.news.models.bulletin_casualty_group import CasualtyScope as StoredCasualtyScope
from app.news.repositories.bulletin_casualty_group_repository import (
    BulletinCasualtyGroupRepository,
)
from app.news.services.clustering.raw_message_embedding_service import strip_boilerplate
from app.news.services.incident_details.category_mapper import (
    compute_rollups,
    map_categories,
    suppress_category_casualties,
)
from app.news.services.matching.emergency_organization_matching_service import (
    EmergencyOrganizationMatchingService,
)
from app.news.services.dedup.fast_path_dedup import (
    MATERIALIZE_MATCH_STATUSES,
    FastPathDedupOutcome,
    FastPathDedupService,
)
from app.news.services.dedup.story_continuation_router import StoryContinuationRouter
from app.news.services.dedup.segment_review_dedup import SegmentReviewDedupService
from app.news.services.pipeline.pipeline_advisory_lock import (
    acquire_fast_path_village_lock,
)
from app.news.services.dedup.fast_path_eligibility import (
    ELIGIBLE_MATCH_STATUSES,
    ERROR_AIR_VIOLATION,
    ERROR_EXACT_HASH,
    ERROR_NO_VILLAGE,
    ERROR_UNMATERIALIZABLE,
    permanent_ineligibility_reason,
)
from app.news.services.materialization.verification_signals import _verification_reason


def _initial_verification_status(
    match_result: dict | None,
    *,
    duplicate_flag: bool = False,
    insufficient_score: bool = False,
    low_confidence_village_match: bool = False,
    condition_review_required: bool = False,
) -> str:
    """Return the initial review state for materialized incidents.

    Relevance uncertainty, casualty-transition ambiguity, and
    low-confidence condition matches do not force manual review here. A
    low-confidence village match does, because the displayed village name is
    otherwise indistinguishable from a full-confidence match.
    """
    return (
        "needs_verification"
        if (
            duplicate_flag
            or insufficient_score
            or low_confidence_village_match
            or condition_review_required
        )
        else "auto_processed"
    )


def _relevance_review_details(
    representative: RawMessage,
) -> tuple[bool, float | None, str | None]:
    filter_result = getattr(representative, "filter_result", None) or {}
    needs_review = bool(
        getattr(representative, "low_confidence_relevance", False)
    ) or bool(filter_result.get("needs_review"))
    return needs_review, filter_result.get("confidence"), filter_result.get("reasoning")


def _relevance_needs_review(representative: RawMessage) -> bool:
    return _relevance_review_details(representative)[0]


logger = logging.getLogger(__name__)
BEIRUT_TIMEZONE = ZoneInfo("Asia/Beirut")


@dataclass(frozen=True)
class _FastPathUnit:
    village_match: dict[str, Any]
    condition_id: int
    condition_status: Any
    casualties: ExtractionCasualties | None
    hash_suffix: str | None
    route_text: str | None
    story_group_id: UUID | None


def _incident_event_datetime(value: datetime) -> datetime:
    """Return the source timestamp in the project's local calendar/time."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(BEIRUT_TIMEZONE)


def _extraction_review_reason(extraction: ExtractionResult) -> str | None:
    if extraction.casualty_scope_needs_review:
        return extraction.casualty_scope_review_reason
    if extraction.needs_review:
        return extraction.review_reason
    return None


EXACT_HASH_CONSTRAINT = "uq_incidents_exact_hash_active"
AMBIGUOUS_SUB_EVENT_SCOPE_REVIEW_REASON = (
    "Multiple sub-events lack explicit location binding in a multi-village bulletin; "
    "ambiguous incident rows were not materialized."
)


def _new_incident_payload(incident: Incident) -> str:
    village = incident.village
    condition = incident.condition
    raw_message = incident.raw_message
    source = incident.source
    source_label = None
    source_reference = None
    if raw_message is not None:
        source_label = (
            raw_message.source_platform.title() if raw_message.source_platform else None
        )
        source_reference = (
            raw_message.origin_account
            or raw_message.source_name
            or raw_message.external_message_id
        )
    if source_label is None and source is not None:
        source_label = source.type.value.title()

    payload = {
        "id": str(incident.id),
        "raw_message_id": incident.raw_message_id,
        "raw_status": raw_message.status.value if raw_message is not None else None,
        "village_id": incident.village_id,
        "story_group_id": (
            str(getattr(incident, "story_group_id", None))
            if getattr(incident, "story_group_id", None)
            else None
        ),
        "condition_id": incident.condition_id,
        "village": (
            getattr(incident, "village_display_name", None)
            or (village.ref_name_en or village.cad_name if village is not None else None)
        ),
        "condition": condition.action_en if condition is not None else None,
        "condition_ar": condition.action_ar if condition is not None else None,
        "event_date": incident.event_date.isoformat(),
        "event_time": incident.event_time.isoformat() if incident.event_time else None,
        "khabar": (incident.khabar or "")[:300],
        "source": source_label,
        "source_reference": source_reference,
        "source_name": raw_message.source_name if raw_message is not None else None,
        "total_deaths": incident.total_deaths,
        "total_injuries": incident.total_injuries,
        "matched": True,
        "verification_status": incident.verification_status,
        "verification_reason": incident.verification_reason,
        "verified_by_user_id": str(incident.verified_by_user_id)
        if incident.verified_by_user_id
        else None,
        "verified_at": incident.verified_at.isoformat()
        if incident.verified_at
        else None,
        "duplicate_flag": "possible" if incident.duplicate_flag else "none",
        "duplicate_level": incident.duplicate_level,
        "duplicate_similarity_score": incident.duplicate_similarity_score,
        "details_pending": incident.details_pending,
        "created_at": incident.created_at.isoformat() if incident.created_at else None,
        "version": incident.version,
        "locked_by_user_id": str(incident.locked_by_user_id)
        if incident.locked_by_user_id
        else None,
        "edit_lock_expires_at": incident.edit_lock_expires_at.isoformat()
        if incident.edit_lock_expires_at
        else None,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _notify_new_incident(db: Session, incident: Incident) -> None:
    try:
        payload = _new_incident_payload(incident)
        with db.begin_nested():
            db.execute(
                text("SELECT pg_notify('new_incident', :payload)"),
                {"payload": payload},
            )
    except Exception:
        logger.exception(
            "Failed to publish new_incident NOTIFY for incident_id=%s",
            incident.id,
        )


@dataclass
class FastMaterializationStats:
    inserted: int = 0
    skipped_ineligible: int = 0
    skipped_air_violation_routed: int = 0
    skipped_duplicate_hash: int = 0
    skipped_confident_duplicate: int = 0
    marked_message_duplicate: int = 0
    marked_unmaterializable: int = 0


@dataclass
class MaterializationStats:
    inserted: int = 0
    skipped_ineligible: int = 0
    skipped_air_violation_routed: int = 0
    skipped_duplicate_hash: int = 0
    merged_into_existing: int = 0


class IncidentMaterializationService:
    def __init__(
        self,
        db: Session,
        dedup_service: DedupMatchingInterface | None = None,
        emergency_org_matcher: EmergencyOrganizationMatchingService | None = None,
        bulletin_groups: BulletinCasualtyGroupRepository | None = None,
        story_router: StoryContinuationRouter | None = None,
        segment_review_service: SegmentReviewDedupService | None = None,
    ) -> None:
        self.db = db
        self.dedup_service = dedup_service
        self.bulletin_groups = bulletin_groups or BulletinCasualtyGroupRepository(db)
        self.emergency_org_matcher = (
            emergency_org_matcher
            or EmergencyOrganizationMatchingService(EmergencyOrganizationRepository(db))
        )
        self.story_router = story_router or StoryContinuationRouter(
            IncidentRepository(db)
        )
        self.segment_review_service = segment_review_service
        self.stats = MaterializationStats()
        self.fast_stats = FastMaterializationStats()

    def process_fast_path(
        self,
        representative: RawMessage,
        fast_dedup: FastPathDedupService,
    ) -> list[Incident]:
        """Tier-1 fast materialize: dedup by village+condition, then insert minimal rows."""
        match_result = self._normalize_match_result(representative.match_result)
        ineligible_reason = permanent_ineligibility_reason(match_result)
        if ineligible_reason is not None:
            if ineligible_reason == ERROR_AIR_VIOLATION:
                self.fast_stats.skipped_air_violation_routed += 1
            else:
                self.fast_stats.skipped_ineligible += 1
            self._mark_unmaterializable(representative, ineligible_reason)
            logger.info(
                "raw_message_id=%s fast_path terminalized: %s",
                representative.id,
                ineligible_reason,
            )
            return []

        assert match_result is not None
        condition_id = self._materializable_condition_id(match_result)
        condition_status = match_result.get("condition_match_status")

        if representative.extraction_result is None:
            raise ValueError(
                f"raw_message id={representative.id} has no extraction_result"
            )
        extraction = ExtractionResult.model_validate(representative.extraction_result)

        message_datetime = representative.message_datetime
        if message_datetime is None:
            raise ValueError(
                f"raw_message id={representative.id} has no message_datetime"
            )
        event_datetime = _incident_event_datetime(message_datetime)

        village_matches: list[dict[str, Any]] = match_result.get("village_matches", [])
        origin_villages = self._origin_village_names(village_matches)
        target_matches = [
            village_match
            for village_match in village_matches
            if self._materializes_village_match(village_match)
        ]
        village_matches, target_matches, extraction = (
            self._collapse_plain_between_targets(
                representative.raw_text,
                village_matches,
                target_matches,
                extraction,
            )
        )
        target_matches = self._dedupe_village_matches_by_village(
            target_matches,
            extraction=extraction,
        )
        is_multi_village = self._distinct_target_village_count(target_matches) > 1
        if self._has_ambiguous_sub_event_scope(
            extraction,
            target_matches,
        ):
            self._mark_raw_message_needs_review(
                representative,
                AMBIGUOUS_SUB_EVENT_SCOPE_REVIEW_REASON,
            )
            logger.warning(
                "raw_message_id=%s skipped ambiguous multi-village sub-events",
                representative.id,
            )
            return []
        self._ensure_bulletin_group(
            representative,
            extraction,
            target_matches=target_matches,
        )

        created: list[Incident] = []
        confident_duplicate_villages = 0
        materializable_villages = 0
        representative_raw_message_id: int | None = None
        units = self._fast_path_units(
            match_result=match_result,
            extraction=extraction,
            village_matches=target_matches,
            root_condition_id=condition_id,
            root_condition_status=condition_status,
            representative_text=representative.raw_text,
        )

        for unit in units:
            village_match = unit.village_match
            condition_id = self._condition_id_for_village(
                unit.village_match, unit.condition_id
            )
            if condition_id is None:
                self.fast_stats.skipped_ineligible += 1
                continue
            condition_status = self._condition_status_for_village(
                unit.village_match,
                unit.condition_status,
            )
            if not self._materializes_village_match(village_match):
                logger.info(
                    "raw_message_id=%s village suppressed from materialization: role=%r text=%r",
                    representative.id,
                    village_match.get("village_role"),
                    village_match.get("raw_village_text"),
                )
                continue
            village_status = village_match.get("village_match_status")
            village_id = self._optional_int(village_match.get("matched_village_id"))
            village_casualties = (
                unit.casualties
                if unit.casualties is not None
                else self._casualties_for_village(
                    extraction,
                    village_match,
                    is_multi_village=is_multi_village,
                )
            )
            village_deaths = village_casualties.deaths
            village_injuries = village_casualties.injuries
            holds_village_lock = (
                village_id is not None and village_status in MATERIALIZE_MATCH_STATUSES
            )
            if holds_village_lock:
                assert village_id is not None
                acquire_fast_path_village_lock(self.db, village_id, condition_id)

            decision = fast_dedup.decide_for_village(
                village_match_status=village_status,
                condition_match_status=condition_status,
                village_id=village_id,
                condition_id=condition_id,
                message_datetime=event_datetime,
                candidate_text=strip_boilerplate(representative.raw_text or ""),
                candidate_embedding=representative.content_embedding,
                exclude_raw_message_id=representative.id,
            )

            if decision.outcome == FastPathDedupOutcome.skip_ineligible:
                self.fast_stats.skipped_ineligible += 1
                if holds_village_lock:
                    self.db.commit()
                logger.info(
                    "raw_message_id=%s village skipped fast_path: village_match_status=%r",
                    representative.id,
                    village_status,
                )
                continue

            materializable_villages += 1

            story_route = None
            if (
                decision.outcome != FastPathDedupOutcome.confident_duplicate
                and isinstance(representative.content_embedding, list)
                and bool(representative.content_embedding)
            ):
                story_route = self.story_router.route_for_village(
                    match_result=match_result,
                    message_datetime=event_datetime,
                    candidate_text=unit.route_text or representative.raw_text,
                    candidate_embedding=representative.content_embedding,
                    exclude_raw_message_id=representative.id,
                    village_id=village_id,
                )

            if (
                story_route is not None
                and story_route.relationship == StoryRelationship.duplicate
            ):
                confident_duplicate_villages += 1
                representative_raw_message_id = story_route.candidate.raw_message_id
                self._merge_into_canonical(
                    fast_dedup=fast_dedup,
                    canonical_incident=story_route.candidate,
                    representative=representative,
                    extraction=extraction,
                    village_casualties=village_casualties,
                    village_deaths=village_deaths,
                    village_injuries=village_injuries,
                    origin_villages=origin_villages,
                    is_multi_village=is_multi_village,
                    similarity_score=1.0,
                    similarity_method="story",
                )
                if holds_village_lock:
                    self.db.commit()
                continue

            if (
                story_route is not None
                and story_route.relationship == StoryRelationship.revision
            ):
                confident_duplicate_villages += 1
                representative_raw_message_id = story_route.candidate.raw_message_id
                revision_casualties = self._revision_casualties_for_route(
                    unit,
                    extraction,
                    village_casualties,
                )
                self.story_router.incidents.apply_story_revision(
                    existing=story_route.candidate,
                    new_candidate_data=self._story_revision_payload(
                        representative=representative,
                        extraction=extraction,
                        village_casualties=revision_casualties,
                        village_deaths=revision_casualties.deaths,
                        village_injuries=revision_casualties.injuries,
                        is_multi_village=is_multi_village,
                    ),
                    raw_message_id=representative.id,
                )
                self.db.commit()
                logger.info(
                    "raw_message_id=%s village_id=%s story revision applied to "
                    "incident_id=%s",
                    representative.id,
                    village_id,
                    story_route.candidate.id,
                )
                if holds_village_lock:
                    self.db.commit()
                continue

            if decision.outcome == FastPathDedupOutcome.possible_duplicate:
                # Flag for human review: materialize the row and link it to the
                # matched active incident with a pending duplicate_matches entry.
                incident = self._insert_fast_incident(
                    representative=representative,
                    casualties=village_casualties,
                    village_id=village_id,
                    village_display_name=self._village_display_name(village_match),
                    condition_id=condition_id,
                    event_datetime=event_datetime,
                    origin_villages=origin_villages,
                    location_qualifier=village_match.get("qualifier_text"),
                    location_ambiguity_note=self._location_ambiguity_note(extraction),
                    deaths=village_deaths,
                    injuries=village_injuries,
                    duplicate_flag=True,
                    scope_review_reason=_extraction_review_reason(extraction),
                    low_confidence_village_match=(
                        village_status == "matched_low_confidence"
                    ),
                    condition_review_required=bool(
                        village_match.get("condition_review_required")
                    ),
                    condition_review_reason=village_match.get(
                        "condition_review_reason"
                    ),
                    hash_suffix=unit.hash_suffix,
                    story_group_id=unit.story_group_id,
                )
                if incident is not None and decision.matched_incident is not None:
                    fast_dedup.incidents.create_duplicate_match(
                        incident=incident,
                        matched_incident=decision.matched_incident,
                        similarity_score=decision.similarity_score or 0.0,
                    )
                    self.db.commit()
                    created.append(incident)
                logger.info(
                    "raw_message_id=%s village_id=%s fast_path possible_duplicate "
                    "matched_incident_id=%s score=%.3f method=%s incident_id=%s",
                    representative.id,
                    village_id,
                    decision.canonical_incident_id,
                    decision.similarity_score or 0.0,
                    decision.similarity_method,
                    incident.id if incident is not None else None,
                )
                if holds_village_lock:
                    self.db.commit()
                continue

            if decision.outcome == FastPathDedupOutcome.confident_duplicate:
                confident_duplicate_villages += 1
                # DuplicateComparisonService is the sole verdict authority on the
                # fast path — do not re-score with DedupMatchingService /
                # dedup_time_window_days (that override reintroduced Mansouri-class
                # false positives).
                canonical_incident = decision.canonical_incident
                if decision.representative_raw_message_id is not None:
                    representative_raw_message_id = (
                        decision.representative_raw_message_id
                    )

                if (
                    self.dedup_service is not None
                    and village_id is not None
                    and canonical_incident is not None
                ):
                    mapped_fields = map_categories(
                        extraction.categories,
                        emergency_org_matcher=self.emergency_org_matcher,
                    )
                    if is_multi_village:
                        mapped_fields, _ = suppress_category_casualties(mapped_fields)
                    total_deaths, total_injuries = compute_rollups(
                        mapped_fields,
                        village_casualties,
                    )
                    score = decision.similarity_score or 0.0
                    try:
                        self.dedup_service.merge_into_incident(
                            existing=canonical_incident,
                            new_candidate_data={
                                "deaths": village_deaths,
                                "injuries": village_injuries,
                                "total_deaths": total_deaths,
                                "total_injuries": total_injuries,
                                "khabar": representative.raw_text or "",
                                "origin_villages": origin_villages,
                                "mapped_fields": mapped_fields,
                                "casualty_transitions": [
                                    item.model_dump(mode="json")
                                    for item in extraction.casualty_transitions
                                ],
                            },
                            raw_message_id=representative.id,
                        )
                        fast_dedup.incidents.create_fast_path_duplicate_match(
                            canonical_incident=canonical_incident,
                            raw_message_id=representative.id,
                            status=MatchStatus.confirmed_duplicate,
                            similarity_score=score,
                        )
                        self.db.commit()
                        logger.info(
                            "raw_message_id=%s village_id=%s fast_path merged into "
                            "incident_id=%s score=%.3f method=%s",
                            representative.id,
                            village_id,
                            canonical_incident.id,
                            score,
                            decision.similarity_method,
                        )
                    except Exception:
                        self.db.rollback()
                        raise
                    if holds_village_lock:
                        self.db.commit()
                    continue

                self.fast_stats.skipped_confident_duplicate += 1
                try:
                    if canonical_incident is not None:
                        # Link-only path keeps the historical kwargs (no score) so
                        # lightweight test doubles and older callers stay valid.
                        fast_dedup.incidents.create_fast_path_duplicate_match(
                            canonical_incident=canonical_incident,
                            raw_message_id=representative.id,
                        )
                    representative.fast_path_completed_at = datetime.now(timezone.utc)
                    self.db.commit()
                except Exception:
                    self.db.rollback()
                    raise
                logger.info(
                    "raw_message_id=%s village_id=%s fast_path confident_duplicate "
                    "canonical_incident_id=%s representative_raw_message_id=%s "
                    "duplicate_match_written=%s (link only; no merge service)",
                    representative.id,
                    village_id,
                    decision.canonical_incident_id,
                    decision.representative_raw_message_id,
                    canonical_incident is not None,
                )
                continue

            incident = self._insert_fast_incident(
                representative=representative,
                casualties=village_casualties,
                village_id=village_id,
                village_display_name=self._village_display_name(village_match),
                condition_id=condition_id,
                event_datetime=event_datetime,
                origin_villages=origin_villages,
                location_qualifier=village_match.get("qualifier_text"),
                location_ambiguity_note=self._location_ambiguity_note(extraction),
                deaths=village_deaths,
                injuries=village_injuries,
                scope_review_reason=_extraction_review_reason(extraction),
                low_confidence_village_match=(
                    village_status == "matched_low_confidence"
                ),
                condition_review_required=bool(
                    village_match.get("condition_review_required")
                ),
                condition_review_reason=village_match.get("condition_review_reason"),
                hash_suffix=unit.hash_suffix,
                story_group_id=unit.story_group_id,
            )
            if incident is not None:
                if self.segment_review_service is not None:
                    self.segment_review_service.queue_for_incident(
                        incident=incident,
                        raw_message_id=representative.id,
                        source_id=representative.source_id,
                        source_name=getattr(representative, "source_name", None),
                        source_platform=getattr(
                            representative,
                            "source_platform",
                            None,
                        ),
                        event_datetime=event_datetime,
                        segment_text=unit.route_text,
                    )
                if (
                    story_route is not None
                    and story_route.relationship == StoryRelationship.distinct_sub_event
                ):
                    self.story_router.incidents.link_story_group(
                        incident,
                        story_route.candidate,
                    )
                    self.db.commit()
                created.append(incident)

        if (
            materializable_villages > 0
            and confident_duplicate_villages == materializable_villages
            and representative_raw_message_id is not None
        ):
            representative.status = MessageStatus.duplicate
            representative.duplicate_of_id = representative_raw_message_id
            now = datetime.now(timezone.utc)
            representative.fast_path_completed_at = now
            representative.materialized_at = now
            representative.error_message = None
            self.db.commit()
            self.fast_stats.marked_message_duplicate += 1
            logger.info(
                "raw_message_id=%s marked duplicate_of_id=%s (all villages confident duplicate)",
                representative.id,
                representative_raw_message_id,
            )
            return created

        if not created and representative.status == MessageStatus.parsed:
            reason = (
                ERROR_EXACT_HASH
                if self.fast_stats.skipped_duplicate_hash > 0
                and materializable_villages > 0
                else ERROR_UNMATERIALIZABLE
            )
            self._mark_unmaterializable(representative, reason)
            logger.info(
                "raw_message_id=%s fast_path terminalized after villages: %s",
                representative.id,
                reason,
            )

        return created

    def _merge_into_canonical(
        self,
        *,
        fast_dedup: FastPathDedupService,
        canonical_incident: Incident,
        representative: RawMessage,
        extraction: ExtractionResult,
        village_casualties: ExtractionCasualties,
        village_deaths: int | None,
        village_injuries: int | None,
        origin_villages: list[str],
        is_multi_village: bool,
        similarity_score: float,
        similarity_method: str,
    ) -> None:
        mapped_fields = map_categories(
            extraction.categories,
            emergency_org_matcher=self.emergency_org_matcher,
        )
        if is_multi_village:
            mapped_fields, _ = suppress_category_casualties(mapped_fields)
        total_deaths, total_injuries = compute_rollups(
            mapped_fields,
            village_casualties,
        )
        payload = {
            "deaths": village_deaths,
            "injuries": village_injuries,
            "total_deaths": total_deaths,
            "total_injuries": total_injuries,
            "khabar": representative.raw_text or "",
            "origin_villages": origin_villages,
            "mapped_fields": mapped_fields,
            "casualty_transitions": [
                item.model_dump(mode="json") for item in extraction.casualty_transitions
            ],
        }
        incidents = (
            getattr(fast_dedup, "incidents", None) or self.story_router.incidents
        )
        try:
            if self.dedup_service is not None:
                self.dedup_service.merge_into_incident(
                    existing=canonical_incident,
                    new_candidate_data=payload,
                    raw_message_id=representative.id,
                )
            else:
                incidents.merge_existing(
                    existing=canonical_incident,
                    new_candidate_data=payload,
                    raw_message_id=representative.id,
                )
            create_match = getattr(incidents, "create_fast_path_duplicate_match", None)
            if create_match is not None:
                create_match(
                    canonical_incident=canonical_incident,
                    raw_message_id=representative.id,
                    status=MatchStatus.confirmed_duplicate,
                    similarity_score=similarity_score,
                )
            self.db.commit()
            logger.info(
                "raw_message_id=%s story/fast-path merged into incident_id=%s "
                "score=%.3f method=%s",
                representative.id,
                canonical_incident.id,
                similarity_score,
                similarity_method,
            )
        except Exception:
            self.db.rollback()
            raise

    def _story_revision_payload(
        self,
        *,
        representative: RawMessage,
        extraction: ExtractionResult,
        village_casualties: ExtractionCasualties,
        village_deaths: int | None,
        village_injuries: int | None,
        is_multi_village: bool,
    ) -> dict[str, Any]:
        mapped_fields = map_categories(
            extraction.categories,
            emergency_org_matcher=self.emergency_org_matcher,
        )
        if is_multi_village:
            mapped_fields, _ = suppress_category_casualties(mapped_fields)
        total_deaths, total_injuries = compute_rollups(
            mapped_fields,
            village_casualties,
        )
        return {
            "deaths": village_deaths,
            "injuries": village_injuries,
            "total_deaths": total_deaths,
            "total_injuries": total_injuries,
            "khabar": representative.raw_text or "",
            "mapped_fields": mapped_fields,
            "male_d": village_casualties.male_deaths,
            "male_i": village_casualties.male_injuries,
            "female_d": village_casualties.female_deaths,
            "female_i": village_casualties.female_injuries,
            "children_d": village_casualties.children_deaths,
            "children_i": village_casualties.children_injuries,
        }

    @staticmethod
    def _revision_casualties_for_route(
        unit: _FastPathUnit,
        extraction: ExtractionResult,
        village_casualties: ExtractionCasualties,
    ) -> ExtractionCasualties:
        # Route endpoints may describe one event, but casualties still belong
        # only to the endpoint whose location entry carries the explicit count.
        return village_casualties

    def _mark_unmaterializable(self, representative: RawMessage, reason: str) -> None:
        """Persist a terminal status in its own transaction.

        Downstream incident-insert failures must not roll this back: the
        concurrent fast-path worker wraps the rest of the unit of work in
        ``except Exception: db.rollback()``.
        """
        if reason == ERROR_AIR_VIOLATION:
            representative.status = MessageStatus.routed_air_violation
        else:
            representative.status = MessageStatus.error
        representative.error_message = reason
        self.fast_stats.marked_unmaterializable += 1
        self.db.commit()

    @classmethod
    def _has_ambiguous_sub_event_scope(
        cls,
        extraction: ExtractionResult,
        target_matches: list[dict[str, Any]],
    ) -> bool:
        if (
            len(extraction.sub_events) < 2
            or cls._distinct_target_village_count(target_matches) < 2
        ):
            return False
        return not any(
            cls._optional_int(match.get("event_index")) is not None
            for match in target_matches
        )

    def _mark_raw_message_needs_review(
        self,
        representative: RawMessage,
        reason: str,
    ) -> None:
        filter_result = dict(getattr(representative, "filter_result", None) or {})
        filter_result["needs_review"] = True
        filter_result["reasoning"] = reason
        representative.filter_result = filter_result
        representative.low_confidence_relevance = True
        representative.fast_path_completed_at = datetime.now(timezone.utc)
        representative.error_message = reason
        # Leaving status=parsed let later stages materialize the held row anyway.
        representative.status = MessageStatus.held_for_review
        self.db.commit()

    @staticmethod
    def _mark_materialized(representative: RawMessage, *, fast_path: bool) -> None:
        representative.status = MessageStatus.materialized
        representative.error_message = None
        now = datetime.now(timezone.utc)
        if fast_path:
            representative.fast_path_completed_at = now
        representative.materialized_at = now

    def _insert_fast_incident(
        self,
        *,
        representative: RawMessage,
        casualties: ExtractionCasualties,
        village_id: int | None,
        village_display_name: str | None,
        condition_id: int,
        event_datetime: datetime,
        origin_villages: list[str],
        location_qualifier: Any,
        location_ambiguity_note: str | None = None,
        deaths: int | None,
        injuries: int | None,
        duplicate_flag: bool = False,
        scope_review_reason: str | None = None,
        low_confidence_village_match: bool = False,
        condition_review_required: bool = False,
        condition_review_reason: str | None = None,
        hash_suffix: str | None = None,
        story_group_id: UUID | None = None,
    ) -> Incident | None:
        if village_id is None:
            self.fast_stats.skipped_ineligible += 1
            return None

        total_deaths, total_injuries = compute_rollups({}, casualties)
        sanitized_khabar = strip_boilerplate(
            strip_emoji_and_pictographs(representative.raw_text or "")
        )

        exact_hash = self._build_exact_hash(
            khabar=sanitized_khabar,
            village_id=village_id,
            condition_id=condition_id,
            event_date=event_datetime.date().isoformat(),
            hash_suffix=hash_suffix,
        )

        verification_status = _initial_verification_status(
            representative.match_result,
            duplicate_flag=duplicate_flag,
            # An insufficient-score duplicate is always created with the
            # duplicate flag, before its audit record is persisted.
            insufficient_score=duplicate_flag,
            low_confidence_village_match=low_confidence_village_match,
            condition_review_required=condition_review_required,
        )
        if scope_review_reason:
            verification_status = "needs_verification"
        verification_reason = scope_review_reason or (
            _verification_reason(
                representative.match_result,
                duplicate_flag=duplicate_flag,
                insufficient_score=duplicate_flag,
                low_confidence_village_match=low_confidence_village_match,
                condition_review_reason=condition_review_reason,
            )
            if verification_status == "needs_verification"
            else None
        )

        incident = Incident(
            raw_message_id=representative.id,
            village_id=village_id,
            village_display_name=village_display_name,
            condition_id=condition_id,
            source_id=representative.source_id,
            event_date=event_datetime.date(),
            event_time=event_datetime.time(),
            khabar=sanitized_khabar,
            khabar_embedding=representative.content_embedding,
            note=self._incident_note(
                origin_villages,
                location_qualifier,
                location_ambiguity_note,
            ),
            total_deaths=total_deaths,
            total_injuries=total_injuries,
            deaths=deaths,
            injuries=injuries,
            exact_hash=exact_hash,
            duplicate_flag=duplicate_flag,
            details_pending=True,
            verification_status=verification_status,
            verification_reason=verification_reason,
            story_group_id=story_group_id,
            created_by=None,
        )

        try:
            self.db.add(incident)
            self.db.flush()
            self.db.add(
                IncidentDetail(
                    incident_id=incident.id,
                    male_d=casualties.male_deaths,
                    male_i=casualties.male_injuries,
                    female_d=casualties.female_deaths,
                    female_i=casualties.female_injuries,
                    children_d=casualties.children_deaths,
                    children_i=casualties.children_injuries,
                )
            )
            self._record_scope_downgrade(
                incident,
                raw_message_id=representative.id,
                reason=scope_review_reason,
            )
            self._mark_materialized(representative, fast_path=True)
            _notify_new_incident(self.db, incident)
            self.db.commit()
            self.fast_stats.inserted += 1
            logger.info(
                "raw_message_id=%s village_id=%s fast_path incident_id=%s details_pending=true",
                representative.id,
                village_id,
                incident.id,
            )
            return incident
        except IntegrityError as exc:
            self.db.rollback()
            if not self._is_exact_hash_conflict(exc):
                raise

            self.fast_stats.skipped_duplicate_hash += 1
            logger.info(
                "fast_path incident already exists for hash raw_message_id=%s village_id=%s",
                representative.id,
                village_id,
            )
            return None
        except Exception:
            self.db.rollback()
            raise

    def materialize(self, representative: RawMessage) -> list[Incident]:
        """Create one Incident per eligible village_match entry.

        Returns a list of successfully inserted (or merged) Incidents (may be
        empty). Ineligible or skipped villages are counted in stats but do not
        abort processing for other villages on the same message.
        """
        match_result = self._normalize_match_result(representative.match_result)
        ineligible_reason = permanent_ineligibility_reason(match_result)
        if ineligible_reason is not None:
            if ineligible_reason == ERROR_AIR_VIOLATION:
                self.stats.skipped_air_violation_routed += 1
            else:
                self.stats.skipped_ineligible += 1
            self._mark_unmaterializable(representative, ineligible_reason)
            logger.info(
                "raw_message_id=%s materialize terminalized: %s",
                representative.id,
                ineligible_reason,
            )
            return []

        assert match_result is not None
        condition_id = self._materializable_condition_id(match_result)

        if representative.extraction_result is None:
            raise ValueError(
                f"raw_message id={representative.id} has no extraction_result"
            )
        extraction = ExtractionResult.model_validate(representative.extraction_result)

        message_datetime = representative.message_datetime
        if message_datetime is None:
            raise ValueError(
                f"raw_message id={representative.id} has no message_datetime"
            )
        event_datetime = _incident_event_datetime(message_datetime)

        casualties = extraction.casualties
        mapped_fields = map_categories(
            extraction.categories,
            emergency_org_matcher=self.emergency_org_matcher,
        )
        created: list[Incident] = []
        materializable_villages = 0
        merged_villages = 0
        canonical_raw_message_id: int | None = None

        village_matches: list[dict[str, Any]] = match_result.get("village_matches", [])
        origin_villages = self._origin_village_names(village_matches)
        target_matches = [
            village_match
            for village_match in village_matches
            if self._materializes_village_match(village_match)
        ]
        village_matches, target_matches, extraction = (
            self._collapse_plain_between_targets(
                representative.raw_text,
                village_matches,
                target_matches,
                extraction,
            )
        )
        target_matches = self._dedupe_village_matches_by_village(
            target_matches,
            extraction=extraction,
        )
        is_multi_village = self._distinct_target_village_count(target_matches) > 1
        category_casualties_suppressed = False
        if is_multi_village:
            mapped_fields, category_casualties_suppressed = (
                suppress_category_casualties(mapped_fields)
            )
        self._ensure_bulletin_group(
            representative,
            extraction,
            target_matches=target_matches,
        )
        if not village_matches:
            self.stats.skipped_ineligible += 1
            self._mark_unmaterializable(representative, ERROR_NO_VILLAGE)
            logger.info(
                "raw_message_id=%s materialize terminalized: %s",
                representative.id,
                ERROR_NO_VILLAGE,
            )
            return []

        event_indexes = {
            index
            for item in target_matches
            if (index := self._optional_int(item.get("event_index"))) is not None
        }
        shared_story_group_id = (
            uuid4()
            if len(event_indexes) >= 2 or (event_indexes and len(target_matches) >= 2)
            else None
        )
        for village_match in target_matches:
            if not self._materializes_village_match(village_match):
                logger.info(
                    "raw_message_id=%s village suppressed from materialization: role=%r text=%r",
                    representative.id,
                    village_match.get("village_role"),
                    village_match.get("raw_village_text"),
                )
                continue
            village_status = village_match.get("village_match_status")
            village_id = self._optional_int(village_match.get("matched_village_id"))
            village_condition_id = self._condition_id_for_village(
                village_match,
                condition_id,
            )
            if village_condition_id is None:
                self.stats.skipped_ineligible += 1
                continue
            village_casualties = self._casualties_for_village(
                extraction,
                village_match,
                is_multi_village=is_multi_village,
            )
            village_deaths = village_casualties.deaths
            village_injuries = village_casualties.injuries
            total_deaths, total_injuries = compute_rollups(
                mapped_fields,
                village_casualties,
            )

            if village_status not in ELIGIBLE_MATCH_STATUSES:
                logger.info(
                    "raw_message_id=%s village skipped: village_match_status=%r",
                    representative.id,
                    village_status,
                )
                self.stats.skipped_ineligible += 1
                continue

            if village_id is None:
                logger.info(
                    "raw_message_id=%s village skipped: matched_village_id is missing",
                    representative.id,
                )
                self.stats.skipped_ineligible += 1
                continue
            materializable_villages += 1

            sanitized_khabar = strip_boilerplate(
                strip_emoji_and_pictographs(representative.raw_text or "")
            )
            exact_hash = self._build_exact_hash(
                khabar=sanitized_khabar,
                village_id=village_id,
                condition_id=village_condition_id,
                event_date=event_datetime.date().isoformat(),
                hash_suffix=self._event_hash_suffix(extraction, village_match),
            )

            # Dedup check: merge into an existing similar incident instead of
            # inserting a new one, if the dedup service is configured.
            khabar_embedding = representative.content_embedding
            duplicate_flag = False
            duplicate_candidate: Incident | None = None
            duplicate_score: float | None = None
            duplicate_level: str | None = None
            if self.dedup_service is not None and khabar_embedding is not None:
                existing, score = self.dedup_service.find_best_match(
                    village_id=village_id,
                    condition_id=village_condition_id,
                    event_date=event_datetime.date(),
                    khabar_embedding=khabar_embedding,
                    exclude_raw_message_id=representative.id,
                    event_time=event_datetime.time(),
                )
                if existing is not None and score >= settings.dedup_high_threshold:
                    try:
                        existing_raw_id = getattr(existing, "raw_message_id", None)
                        if existing_raw_id is not None:
                            canonical_raw_message_id = existing_raw_id
                        existing.duplicate_level = "high"
                        existing.duplicate_similarity_score = score
                        if category_casualties_suppressed:
                            existing.verification_status = "needs_verification"
                            existing.verification_reason = (
                                "Category casualties require manual per-village "
                                "confirmation for a multi-target bulletin"
                            )
                        if extraction.casualty_scope_needs_review:
                            existing.verification_status = "needs_verification"
                            existing.verification_reason = (
                                extraction.casualty_scope_review_reason
                            )
                            self._record_scope_downgrade(
                                existing,
                                raw_message_id=representative.id,
                                reason=extraction.casualty_scope_review_reason,
                            )
                        self.dedup_service.merge_into_incident(
                            existing=existing,
                            new_candidate_data={
                                "deaths": village_deaths,
                                "injuries": village_injuries,
                                "total_deaths": total_deaths,
                                "total_injuries": total_injuries,
                                "khabar": representative.raw_text or "",
                                "origin_villages": origin_villages,
                                "mapped_fields": mapped_fields,
                                "casualty_transitions": [
                                    item.model_dump(mode="json")
                                    for item in extraction.casualty_transitions
                                ],
                            },
                            raw_message_id=representative.id,
                        )
                        self.db.commit()
                        merged_villages += 1
                        created.append(existing)
                        if existing_raw_id is None:
                            self._mark_materialized(representative, fast_path=False)
                        self.stats.merged_into_existing += 1
                        logger.info(
                            "raw_message_id=%s village_id=%s merged into "
                            "incident_id=%s score=%.3f",
                            representative.id,
                            village_id,
                            existing.id,
                            score,
                        )
                        continue
                    except Exception:
                        self.db.rollback()
                        raise
                if existing is not None and score >= settings.dedup_low_threshold:
                    duplicate_flag = True
                    duplicate_level = "medium"
                    duplicate_candidate = existing
                    duplicate_score = score
                    logger.info(
                        "raw_message_id=%s village_id=%s dedup_flag: score=%.3f "
                        "possible_duplicate_of_incident_id=%s",
                        representative.id,
                        village_id,
                        score,
                        existing.id,
                    )
                elif existing is not None:
                    duplicate_level = "low"
                    duplicate_score = score

            verification_status = _initial_verification_status(
                representative.match_result,
                duplicate_flag=duplicate_flag,
                low_confidence_village_match=(
                    village_status == "matched_low_confidence"
                ),
                condition_review_required=bool(
                    village_match.get("condition_review_required")
                ),
            )
            extraction_review_reason = _extraction_review_reason(extraction)
            if category_casualties_suppressed or extraction_review_reason:
                verification_status = "needs_verification"
            verification_reason = (
                extraction_review_reason
                if extraction_review_reason
                else "Category casualties require manual per-village confirmation "
                "for a multi-target bulletin"
                if category_casualties_suppressed
                else _verification_reason(
                    representative.match_result,
                    duplicate_flag=duplicate_flag,
                    duplicate_level=duplicate_level,
                    duplicate_similarity_score=duplicate_score,
                    low_confidence_village_match=(
                        village_status == "matched_low_confidence"
                    ),
                    condition_review_reason=village_match.get(
                        "condition_review_reason"
                    ),
                )
                if verification_status == "needs_verification"
                else None
            )

            incident = Incident(
                raw_message_id=representative.id,
                village_id=village_id,
                village_display_name=self._village_display_name(village_match),
                condition_id=village_condition_id,
                source_id=representative.source_id,
                event_date=event_datetime.date(),
                event_time=event_datetime.time(),
                khabar=sanitized_khabar,
                khabar_embedding=khabar_embedding,
                note=self._incident_note(
                    origin_villages,
                    village_match.get("qualifier_text"),
                    self._location_ambiguity_note(extraction),
                ),
                total_deaths=total_deaths,
                total_injuries=total_injuries,
                deaths=village_deaths,
                injuries=village_injuries,
                exact_hash=exact_hash,
                duplicate_flag=duplicate_flag,
                duplicate_level=duplicate_level,
                duplicate_similarity_score=duplicate_score,
                verification_status=verification_status,
                verification_reason=verification_reason,
                story_group_id=shared_story_group_id,
                created_by=None,
            )

            try:
                self.db.add(incident)
                self.db.flush()
                if (
                    self.dedup_service is not None
                    and duplicate_candidate is not None
                    and duplicate_score is not None
                ):
                    self.dedup_service.record_possible_duplicate(
                        incident=incident,
                        matched_incident=duplicate_candidate,
                        similarity_score=duplicate_score,
                    )
                self.db.add(
                    IncidentDetail(
                        incident_id=incident.id,
                        male_d=village_casualties.male_deaths,
                        male_i=village_casualties.male_injuries,
                        female_d=village_casualties.female_deaths,
                        female_i=village_casualties.female_injuries,
                        children_d=village_casualties.children_deaths,
                        children_i=village_casualties.children_injuries,
                        **mapped_fields,
                    )
                )
                self._record_scope_downgrade(
                    incident,
                    raw_message_id=representative.id,
                    reason=extraction.casualty_scope_review_reason
                    if extraction.casualty_scope_needs_review
                    else None,
                )
                self._mark_materialized(representative, fast_path=False)
                _notify_new_incident(self.db, incident)
                self.db.commit()
                self.stats.inserted += 1
                created.append(incident)
            except IntegrityError as exc:
                self.db.rollback()
                if not self._is_exact_hash_conflict(exc):
                    raise

                existing = self.db.scalar(
                    select(Incident).where(
                        Incident.exact_hash == exact_hash,
                        Incident.is_deleted.is_(False),
                    )
                )
                existing_id = existing.id if existing is not None else None
                if existing is not None:
                    merged_villages += 1
                    existing_raw_id = getattr(existing, "raw_message_id", None)
                    if existing_raw_id is not None:
                        canonical_raw_message_id = existing_raw_id
                self.stats.skipped_duplicate_hash += 1
                logger.info(
                    "incident already exists for this hash, skipping "
                    "raw_message_id=%s village_id=%s existing_incident_id=%s",
                    representative.id,
                    village_id,
                    existing_id,
                )
            except Exception:
                self.db.rollback()
                raise

        if (
            materializable_villages > 0
            and merged_villages == materializable_villages
            and canonical_raw_message_id is not None
        ):
            representative.status = MessageStatus.duplicate
            representative.duplicate_of_id = canonical_raw_message_id
            representative.error_message = None
            representative.materialized_at = datetime.now(timezone.utc)
            self.db.commit()

        return created

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_match_result(
        match_result: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Upgrade an old flat match_result (pre-Task-4) to the village_matches shape."""
        if not match_result:
            return None
        if "village_matches" in match_result:
            return match_result
        # Old flat shape — wrap the single village entry in a list.
        village_match: dict[str, Any] = {
            "matched_village_id": match_result.get("matched_village_id"),
            "village_confidence": match_result.get("village_confidence"),
            "village_match_status": match_result.get(
                "village_match_status", "unmatched"
            ),
            "village_review_required": match_result.get(
                "village_review_required", True
            ),
            "raw_village_text": match_result.get("raw_village_text"),
            "village_role": match_result.get("village_role", VillageRole.target.value),
            "alias_matched": match_result.get("alias_matched", False),
        }
        return {**match_result, "village_matches": [village_match]}

    @staticmethod
    def _required_int(payload: dict[str, Any], key: str) -> int:
        value = IncidentMaterializationService._optional_int(payload.get(key))
        if value is None:
            raise ValueError(f"{key} must be a non-null integer")
        return value

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value

    def _fast_path_units(
        self,
        *,
        match_result: dict[str, Any],
        extraction: ExtractionResult,
        village_matches: list[dict[str, Any]],
        root_condition_id: int,
        root_condition_status: Any,
        representative_text: str | None,
    ) -> list[_FastPathUnit]:
        """Build only declared location/action pairs; never a Cartesian product."""
        indexed_matches = [
            item
            for item in village_matches
            if self._optional_int(item.get("event_index")) is not None
        ]
        if indexed_matches:
            event_indexes = {
                index
                for item in indexed_matches
                if (index := self._optional_int(item.get("event_index"))) is not None
            }
            shared_group = (
                uuid4()
                if len(event_indexes) >= 2 or len(indexed_matches) >= 2
                else None
            )
            units: list[_FastPathUnit] = []
            for village_match in indexed_matches:
                index = self._optional_int(village_match.get("event_index"))
                if index is None or not 0 <= index < len(extraction.sub_events):
                    continue
                condition_id = self._condition_id_for_village(
                    village_match,
                    root_condition_id,
                )
                if condition_id is None:
                    continue
                sub_event = extraction.sub_events[index]
                units.append(
                    _FastPathUnit(
                        village_match=village_match,
                        condition_id=condition_id,
                        condition_status=self._condition_status_for_village(
                            village_match,
                            root_condition_status,
                        ),
                        casualties=self._event_casualties_for_match(
                            sub_event,
                            village_match,
                        ),
                        hash_suffix=self._event_hash_suffix(extraction, village_match),
                        route_text=sub_event.evidence_span or representative_text,
                        story_group_id=shared_group,
                    )
                )
            return units

        paired: list[tuple[int, ExtractionSubEvent, dict[str, Any], int]] = []
        sub_matches = match_result.get("sub_event_matches") or []
        by_index: dict[int, dict[str, Any]] = {}
        for item in sub_matches:
            if not isinstance(item, dict):
                continue
            index = item.get("index")
            if isinstance(index, int) and not isinstance(index, bool):
                by_index[index] = item
        for index, sub_event in enumerate(extraction.sub_events):
            match = by_index.get(index)
            if match is None and index < len(sub_matches):
                fallback = sub_matches[index]
                if isinstance(fallback, dict):
                    match = fallback
            condition_id = self._optional_int((match or {}).get("matched_condition_id"))
            if condition_id is None:
                continue
            paired.append((index, sub_event, match or {}, condition_id))

        if (
            village_matches
            and self._distinct_target_village_count(village_matches) == 1
            and len(paired) >= 2
        ):
            shared_group = uuid4()
            village_match = village_matches[0]
            units: list[_FastPathUnit] = []
            for index, sub_event, match, sub_condition_id in paired:
                suffix = (sub_event.evidence_span or f"sub-{index}").strip()[:80]
                units.append(
                    _FastPathUnit(
                        village_match=village_match,
                        condition_id=sub_condition_id,
                        condition_status=match.get(
                            "condition_match_status",
                            root_condition_status,
                        ),
                        casualties=sub_event.casualties,
                        hash_suffix=suffix,
                        route_text=sub_event.evidence_span or representative_text,
                        story_group_id=shared_group,
                    )
                )
            return units

        if len(village_matches) > 1 and len(paired) >= 2:
            return []

        units: list[_FastPathUnit] = []
        for village_match in village_matches:
            condition_id = self._condition_id_for_village(
                village_match,
                root_condition_id,
            )
            if condition_id is None:
                continue
            units.append(
                _FastPathUnit(
                    village_match=village_match,
                    condition_id=condition_id,
                    condition_status=self._condition_status_for_village(
                        village_match,
                        root_condition_status,
                    ),
                    casualties=None,
                    hash_suffix=None,
                    route_text=representative_text,
                    story_group_id=None,
                )
            )
        return units

    @classmethod
    def _condition_id_for_village(
        cls,
        village_match: dict[str, Any],
        fallback: int,
    ) -> int | None:
        """Prefer a per-village/sub-event condition; otherwise use message-level.

        Sub-events often carry ``event_index`` even when condition matching for
        that clause failed (``unmatched``). Dropping those villages left
        multi-event bulletins (ACCSTUDY-002) as a single row. Falling back to
        the message-level matched condition keeps one row per village.
        """
        condition_id = cls._optional_int(village_match.get("matched_condition_id"))
        if condition_id is not None:
            return condition_id
        return fallback

    @staticmethod
    def _condition_status_for_village(
        village_match: dict[str, Any],
        fallback: Any,
    ) -> Any:
        return village_match.get("condition_match_status") or fallback

    @classmethod
    def _materializable_condition_id(cls, match_result: dict[str, Any]) -> int:
        root = cls._optional_int(match_result.get("matched_condition_id"))
        if root is not None:
            return root
        for village_match in match_result.get("village_matches") or []:
            if not isinstance(village_match, dict):
                continue
            condition_id = cls._optional_int(village_match.get("matched_condition_id"))
            if condition_id is not None:
                return condition_id
        raise ValueError("match_result has no materializable condition id")

    @classmethod
    def _distinct_target_village_count(
        cls,
        target_matches: list[dict[str, Any]],
    ) -> int:
        return len(
            {
                village_id
                for item in target_matches
                if (village_id := cls._optional_int(item.get("matched_village_id")))
                is not None
            }
        )

    @classmethod
    def _dedupe_village_matches_by_village(
        cls,
        village_matches: list[dict[str, Any]],
        *,
        extraction: ExtractionResult | None = None,
    ) -> list[dict[str, Any]]:
        """Drop Cartesian duplicates without collapsing distinct same-village actions.

        ACCSTUDY-005-style extractions put every list village into each
        sub-event's ``locations``, so matching emits the same village under
        many ``event_index`` values. Keep every match whose sub-event action
        names that village (distinct actions on one place stay), otherwise
        prefer sole-location clauses, else the first occurrence.
        """
        if len(village_matches) < 2:
            return list(village_matches)

        sub_events = extraction.sub_events if extraction is not None else []

        def _action_mentions(match: dict[str, Any]) -> bool:
            raw = match.get("raw_village_text")
            if not isinstance(raw, str) or not raw.strip():
                return False
            index = cls._optional_int(match.get("event_index"))
            if index is None or not 0 <= index < len(sub_events):
                return False
            action = (
                getattr(sub_events[index], "action_text", None)
                or getattr(sub_events[index], "action_description", None)
                or ""
            ).strip()
            return bool(action) and raw.strip() in action

        def _is_sole_location(match: dict[str, Any]) -> bool:
            location_count = cls._optional_int(match.get("event_location_count"))
            if location_count is not None:
                return location_count <= 1
            index = cls._optional_int(match.get("event_index"))
            if index is None:
                return True
            same_event = sum(
                1
                for other in village_matches
                if cls._optional_int(other.get("event_index")) == index
            )
            return same_event <= 1

        groups: dict[str, list[dict[str, Any]]] = {}
        order: list[str] = []
        for match in village_matches:
            village_id = cls._optional_int(match.get("matched_village_id"))
            if village_id is not None:
                key = f"id:{village_id}"
            else:
                raw = match.get("raw_village_text")
                if not isinstance(raw, str) or not raw.strip():
                    continue
                key = f"text:{raw.strip()}"
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(match)

        deduped: list[dict[str, Any]] = []
        for key in order:
            group = groups[key]
            if len(group) == 1:
                deduped.append(group[0])
                continue
            mentioned = [match for match in group if _action_mentions(match)]
            if mentioned:
                deduped.extend(mentioned)
                continue
            sole = [match for match in group if _is_sole_location(match)]
            if sole:
                deduped.extend(sole)
                continue
            deduped.append(group[0])
        return deduped

    @classmethod
    def _event_casualties_for_match(
        cls,
        sub_event: ExtractionSubEvent,
        village_match: dict[str, Any],
    ) -> ExtractionCasualties:
        deaths = cls._optional_int(village_match.get("deaths"))
        injuries = cls._optional_int(village_match.get("injuries"))
        location_count = cls._optional_int(village_match.get("event_location_count"))
        if location_count is not None and location_count > 1:
            if deaths is None and injuries is None:
                return ExtractionCasualties()
            return sub_event.casualties.model_copy(
                update={
                    "deaths": deaths,
                    "total_deaths": deaths,
                    "injuries": injuries,
                    "total_injuries": injuries,
                }
            )
        return sub_event.casualties.model_copy(
            update={
                "deaths": (
                    deaths if deaths is not None else sub_event.casualties.deaths
                ),
                "injuries": (
                    injuries if injuries is not None else sub_event.casualties.injuries
                ),
            }
        )

    @classmethod
    def _casualties_for_village(
        cls,
        extraction: ExtractionResult,
        village_match: dict[str, Any],
        *,
        is_multi_village: bool,
    ) -> ExtractionCasualties:
        event_index = cls._optional_int(village_match.get("event_index"))
        if event_index is not None and 0 <= event_index < len(extraction.sub_events):
            return cls._event_casualties_for_match(
                extraction.sub_events[event_index],
                village_match,
            )
        return cls._root_casualties_for_village(
            village_match,
            extraction.casualties,
            is_multi_village=is_multi_village,
        )

    @classmethod
    def _event_hash_suffix(
        cls,
        extraction: ExtractionResult,
        village_match: dict[str, Any],
    ) -> str | None:
        event_index = cls._optional_int(village_match.get("event_index"))
        if event_index is None or not 0 <= event_index < len(extraction.sub_events):
            return None
        sub_event = extraction.sub_events[event_index]
        return (sub_event.evidence_span or f"sub-{event_index}").strip()[:80]

    @staticmethod
    def _root_casualties_for_village(
        village_match: dict[str, Any],
        casualties: ExtractionCasualties,
        *,
        is_multi_village: bool,
    ) -> ExtractionCasualties:
        deaths = IncidentMaterializationService._optional_int(
            village_match.get("deaths")
        )
        injuries = IncidentMaterializationService._optional_int(
            village_match.get("injuries")
        )
        if is_multi_village:
            # Null is meaningful here: it means this village had no explicit
            # local count. Falling back to the bulletin total would recreate
            # the multi-village casualty misattribution bug.
            return ExtractionCasualties(deaths=deaths, injuries=injuries)
        return casualties.model_copy(
            update={
                "deaths": deaths if deaths is not None else casualties.deaths,
                "injuries": (injuries if injuries is not None else casualties.injuries),
            }
        )

    def _ensure_bulletin_group(
        self,
        representative: RawMessage,
        extraction: ExtractionResult,
        *,
        target_matches: list[dict[str, Any]],
    ) -> None:
        if (
            extraction.casualty_scope != CasualtyScope.bulletin_aggregate
            or len(target_matches) <= 1
        ):
            return
        village_ids = sorted(
            {
                village_id
                for item in target_matches
                if isinstance((village_id := item.get("matched_village_id")), int)
                and not isinstance(village_id, bool)
            }
        )
        if len(village_ids) <= 1:
            return
        self.bulletin_groups.create_for_message(
            raw_message_id=representative.id,
            village_ids=village_ids,
            casualty_scope=StoredCasualtyScope.bulletin_aggregate,
            total_deaths=extraction.casualties.total_deaths,
            total_injuries=extraction.casualties.total_injuries,
            created_at=representative.message_datetime,
        )

    def _record_scope_downgrade(
        self,
        incident: Incident,
        *,
        raw_message_id: int,
        reason: str | None,
    ) -> None:
        if not reason:
            return
        already_recorded = self.db.scalar(
            select(IncidentUpdate.id).where(
                IncidentUpdate.incident_id == incident.id,
                IncidentUpdate.action == UpdateAction.pipeline_merge,
                IncidentUpdate.new_values["casualty_scope_source_raw_message_id"].astext
                == str(raw_message_id),
            )
        )
        if already_recorded is not None:
            return
        self.db.add(
            IncidentUpdate(
                incident_id=incident.id,
                action=UpdateAction.pipeline_merge,
                old_values={"casualty_scope": "unsupported_model_claim"},
                new_values={
                    "casualty_scope": CasualtyScope.unspecified.value,
                    "casualty_scope_source_raw_message_id": raw_message_id,
                    "downgrade_reason": reason,
                },
                performed_by=None,
            )
        )

    @staticmethod
    def _materializes_village_match(village_match: dict[str, Any]) -> bool:
        return (
            village_match.get("village_role", VillageRole.target.value)
            == VillageRole.target.value
        )

    @staticmethod
    def _origin_village_names(village_matches: list[dict[str, Any]]) -> list[str]:
        origin_villages: list[str] = []
        for village_match in village_matches:
            if village_match.get("village_role") != VillageRole.origin.value:
                continue
            raw_text = village_match.get("raw_village_text")
            if not isinstance(raw_text, str):
                continue
            normalized = raw_text.strip()
            if normalized and normalized not in origin_villages:
                origin_villages.append(normalized)
        return origin_villages

    @classmethod
    def _collapse_plain_between_targets(
        cls,
        raw_text: str | None,
        village_matches: list[dict[str, Any]],
        target_matches: list[dict[str, Any]],
        extraction: ExtractionResult,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], ExtractionResult]:
        """Collapse plain بين/محيط/قرب phrasing to one reviewable target village."""
        if cls._distinct_target_village_count(target_matches) <= 1:
            return village_matches, target_matches, extraction

        fuzzy = cls._plain_fuzzy_area_target_order(raw_text, target_matches)
        if fuzzy is None:
            return village_matches, target_matches, extraction

        primary, alternate_matches, evidence = fuzzy
        alternatives = [
            str(item.get("raw_village_text") or "").strip()
            for item in alternate_matches
            if str(item.get("raw_village_text") or "").strip()
        ]
        collapsed_primary = {
            **primary,
            "village_match_status": "matched_low_confidence",
            "village_review_required": True,
            "qualifier_text": primary.get("qualifier_text")
            or f"fuzzy area; alternate: {', '.join(alternatives)}",
        }
        primary_id = id(primary)
        alternate_ids = {id(item) for item in alternate_matches}
        collapsed_village_matches: list[dict[str, Any]] = []
        for item in village_matches:
            if id(item) == primary_id:
                collapsed_village_matches.append(collapsed_primary)
            elif id(item) in alternate_ids:
                continue
            else:
                collapsed_village_matches.append(item)

        merged_alternatives = list(extraction.location_alternatives)
        merged_alternatives.extend(
            item for item in alternatives if item not in merged_alternatives
        )
        collapsed_extraction = extraction.model_copy(
            update={
                "location_ambiguity": True,
                "location_alternatives": merged_alternatives,
                "location_ambiguity_evidence": (
                    extraction.location_ambiguity_evidence or evidence
                ),
            }
        )
        collapsed_target_matches = [
            collapsed_primary if id(item) == primary_id else item
            for item in target_matches
            if id(item) not in alternate_ids
        ]
        return collapsed_village_matches, collapsed_target_matches, collapsed_extraction

    @staticmethod
    def _plain_fuzzy_area_target_order(
        raw_text: str | None,
        target_matches: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], list[dict[str, Any]], str] | None:
        normalized_text = normalize_arabic_text(raw_text or "")
        if not normalized_text:
            return None
        marker = re.search(
            r"(?:^|\s)(?:في\s+)?(?:المنطقه\s+الواقعه\s+)?"
            r"(?:محيط|قرب|بالقرب\s+من|بين(?:\s+بلدتي)?)\s+",
            normalized_text,
        )
        if marker is None:
            return None
        before = normalized_text[max(0, marker.start() - 16) : marker.start()]
        if "طريق" in before or "مسار" in before:
            return None

        tail = re.split(r"[،؛:.!؟\n]", normalized_text[marker.end() :], maxsplit=1)[0]
        ordered = sorted(
            (
                (tail.find(name), item, name)
                for item in target_matches
                if (
                    name := normalize_arabic_text(
                        str(item.get("raw_village_text") or "")
                    )
                )
                and name in tail
            ),
            key=lambda value: value[0],
        )
        if len(ordered) < 2:
            return None

        primary = ordered[0][1]
        alternatives = [ordered[1][1]]
        evidence = normalized_text[marker.start() :].strip()
        return primary, alternatives, evidence

    @staticmethod
    def _origin_village_note(origin_villages: list[str]) -> str | None:
        if not origin_villages:
            return None
        if len(origin_villages) == 1:
            return f"Origin village: {origin_villages[0]}"
        joined = ", ".join(origin_villages)
        return f"Origin villages: {joined}"

    @classmethod
    def _incident_note(
        cls,
        origin_villages: list[str],
        qualifier_text: Any,
        location_ambiguity_note: str | None = None,
    ) -> str | None:
        parts = [cls._origin_village_note(origin_villages)]
        if isinstance(qualifier_text, str) and qualifier_text.strip():
            parts.append(f"Location qualifier: {qualifier_text.strip()}")
        if location_ambiguity_note:
            parts.append(location_ambiguity_note)
        return "\n".join(part for part in parts if part) or None

    @staticmethod
    def _location_ambiguity_note(extraction: ExtractionResult) -> str | None:
        if not extraction.location_ambiguity or not extraction.location_alternatives:
            return None
        alternatives = ", ".join(extraction.location_alternatives)
        evidence = extraction.location_ambiguity_evidence
        suffix = f" Evidence: {evidence}" if evidence else ""
        return f"Location ambiguity: fuzzy area; alternate village(s): {alternatives}.{suffix}"

    @staticmethod
    def _build_exact_hash(
        khabar: str,
        village_id: int,
        condition_id: int,
        event_date: str,
        hash_suffix: str | None = None,
    ) -> str:
        normalized = " ".join(khabar.split())
        key = f"{normalized}|{village_id}|{condition_id}|{event_date}"
        if hash_suffix:
            key = f"{key}|{hash_suffix}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    @staticmethod
    def _is_exact_hash_conflict(exc: IntegrityError) -> bool:
        diagnostic = getattr(exc.orig, "diag", None)
        constraint_name = getattr(diagnostic, "constraint_name", None)
        return constraint_name == EXACT_HASH_CONSTRAINT
