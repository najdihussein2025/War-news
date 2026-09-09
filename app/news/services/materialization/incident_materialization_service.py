from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.text_sanitizer import strip_emoji_and_pictographs
from app.llm.dtos import ExtractionCasualties, ExtractionResult, VillageRole
from app.news.interfaces import DedupMatchingInterface
from app.news.models import Incident, IncidentDetail, MatchStatus, MessageStatus, RawMessage
from app.news.repositories.emergency_organization_repository import (
    EmergencyOrganizationRepository,
)
from app.news.services.clustering.raw_message_embedding_service import strip_boilerplate
from app.news.services.incident_details.category_mapper import compute_rollups, map_categories
from app.news.services.matching.emergency_organization_matching_service import (
    EmergencyOrganizationMatchingService,
)
from app.news.services.dedup.fast_path_dedup import (
    MATERIALIZE_MATCH_STATUSES,
    FastPathDedupOutcome,
    FastPathDedupService,
)
from app.news.services.pipeline.pipeline_advisory_lock import acquire_fast_path_village_lock
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
) -> str:
    """Return the initial review state — duplicate signals only.

    Verification is reserved for possible-duplicate cases. Relevance
    uncertainty, casualty-transition ambiguity, and low-confidence
    village/condition matches no longer force manual review; they
    materialize as auto_processed. (`match_result` is kept as a parameter
    for call-site compatibility even though it's unused here — do not
    remove it without also updating both call sites.)
    """
    return "needs_verification" if (duplicate_flag or insufficient_score) else "auto_processed"


def _relevance_review_details(
    representative: RawMessage,
) -> tuple[bool, float | None, str | None]:
    filter_result = getattr(representative, "filter_result", None) or {}
    needs_review = bool(getattr(representative, "low_confidence_relevance", False)) or bool(
        filter_result.get("needs_review")
    )
    return needs_review, filter_result.get("confidence"), filter_result.get("reasoning")


def _relevance_needs_review(representative: RawMessage) -> bool:
    return _relevance_review_details(representative)[0]

logger = logging.getLogger(__name__)
BEIRUT_TIMEZONE = ZoneInfo("Asia/Beirut")


def _incident_event_datetime(value: datetime) -> datetime:
    """Return the source timestamp in the project's local calendar/time."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(BEIRUT_TIMEZONE)

EXACT_HASH_CONSTRAINT = "uq_incidents_exact_hash_active"


def _new_incident_payload(incident: Incident) -> str:
    village = incident.village
    condition = incident.condition
    raw_message = incident.raw_message
    source = incident.source
    source_label = None
    source_reference = None
    if raw_message is not None:
        source_label = (
            raw_message.source_platform.title()
            if raw_message.source_platform
            else None
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
        "condition_id": incident.condition_id,
        "village": (
            village.ref_name_en or village.cad_name if village is not None else None
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
        "verified_by_user_id": str(incident.verified_by_user_id) if incident.verified_by_user_id else None,
        "verified_at": incident.verified_at.isoformat() if incident.verified_at else None,
        "duplicate_flag": "possible" if incident.duplicate_flag else "none",
        "duplicate_level": incident.duplicate_level,
        "duplicate_similarity_score": incident.duplicate_similarity_score,
        "details_pending": incident.details_pending,
        "created_at": incident.created_at.isoformat() if incident.created_at else None,
        "version": incident.version,
        "locked_by_user_id": str(incident.locked_by_user_id) if incident.locked_by_user_id else None,
        "edit_lock_expires_at": incident.edit_lock_expires_at.isoformat() if incident.edit_lock_expires_at else None,
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
    ) -> None:
        self.db = db
        self.dedup_service = dedup_service
        self.emergency_org_matcher = (
            emergency_org_matcher
            or EmergencyOrganizationMatchingService(
                EmergencyOrganizationRepository(db)
            )
        )
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
        condition_id = self._required_int(match_result, "matched_condition_id")
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
        is_multi_village = len(target_matches) > 1

        created: list[Incident] = []
        confident_duplicate_villages = 0
        materializable_villages = 0
        representative_raw_message_id: int | None = None

        for village_match in village_matches:
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
            village_deaths, village_injuries = self._root_casualties_for_village(
                village_match,
                extraction.casualties,
                is_multi_village=is_multi_village,
            )
            holds_village_lock = (
                village_id is not None
                and village_status in MATERIALIZE_MATCH_STATUSES
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

            if decision.outcome == FastPathDedupOutcome.possible_duplicate:
                # Flag for human review: materialize the row and link it to the
                # matched active incident with a pending duplicate_matches entry.
                incident = self._insert_fast_incident(
                    representative=representative,
                    extraction=extraction,
                    village_id=village_id,
                    condition_id=condition_id,
                    event_datetime=event_datetime,
                    origin_villages=origin_villages,
                    deaths=village_deaths,
                    injuries=village_injuries,
                    duplicate_flag=True,
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
                    representative_raw_message_id = decision.representative_raw_message_id

                if (
                    self.dedup_service is not None
                    and village_id is not None
                    and canonical_incident is not None
                ):
                    mapped_fields = map_categories(
                        extraction.categories,
                        emergency_org_matcher=self.emergency_org_matcher,
                    )
                    casualties = extraction.casualties
                    total_deaths, total_injuries = compute_rollups(
                        mapped_fields,
                        casualties,
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
                extraction=extraction,
                village_id=village_id,
                condition_id=condition_id,
                event_datetime=event_datetime,
                origin_villages=origin_villages,
                deaths=village_deaths,
                injuries=village_injuries,
            )
            if incident is not None:
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
        extraction: ExtractionResult,
        village_id: int | None,
        condition_id: int,
        event_datetime: datetime,
        origin_villages: list[str],
        deaths: int | None,
        injuries: int | None,
        duplicate_flag: bool = False,
    ) -> Incident | None:
        if village_id is None:
            self.fast_stats.skipped_ineligible += 1
            return None

        casualties = extraction.casualties
        total_deaths, total_injuries = compute_rollups({}, casualties)
        sanitized_khabar = strip_boilerplate(
            strip_emoji_and_pictographs(representative.raw_text or "")
        )

        exact_hash = self._build_exact_hash(
            khabar=sanitized_khabar,
            village_id=village_id,
            condition_id=condition_id,
            event_date=event_datetime.date().isoformat(),
        )

        verification_status = _initial_verification_status(
            representative.match_result,
            duplicate_flag=duplicate_flag,
            # An insufficient-score duplicate is always created with the
            # duplicate flag, before its audit record is persisted.
            insufficient_score=duplicate_flag,
        )

        incident = Incident(
            raw_message_id=representative.id,
            village_id=village_id,
            condition_id=condition_id,
            source_id=representative.source_id,
            event_date=event_datetime.date(),
            event_time=event_datetime.time(),
            khabar=sanitized_khabar,
            khabar_embedding=representative.content_embedding,
            note=self._origin_village_note(origin_villages),
            total_deaths=total_deaths,
            total_injuries=total_injuries,
            deaths=deaths,
            injuries=injuries,
            exact_hash=exact_hash,
            duplicate_flag=duplicate_flag,
            details_pending=True,
            verification_status=verification_status,
            verification_reason=_verification_reason(
                representative.match_result,
                duplicate_flag=duplicate_flag,
                insufficient_score=duplicate_flag,
            )
            if verification_status == "needs_verification"
            else None,
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
        condition_id = self._required_int(match_result, "matched_condition_id")

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
        total_deaths, total_injuries = compute_rollups(mapped_fields, casualties)
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
        is_multi_village = len(target_matches) > 1
        if not village_matches:
            self.stats.skipped_ineligible += 1
            self._mark_unmaterializable(representative, ERROR_NO_VILLAGE)
            logger.info(
                "raw_message_id=%s materialize terminalized: %s",
                representative.id,
                ERROR_NO_VILLAGE,
            )
            return []

        for village_match in village_matches:
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
            village_deaths, village_injuries = self._root_casualties_for_village(
                village_match,
                casualties,
                is_multi_village=is_multi_village,
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
                condition_id=condition_id,
                event_date=event_datetime.date().isoformat(),
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
                    condition_id=condition_id,
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
                            self._mark_materialized(
                                representative, fast_path=False
                            )
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
                if (
                    existing is not None
                    and score >= settings.dedup_low_threshold
                ):
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
            )

            incident = Incident(
                raw_message_id=representative.id,
                village_id=village_id,
                condition_id=condition_id,
                source_id=representative.source_id,
                event_date=event_datetime.date(),
                event_time=event_datetime.time(),
                khabar=sanitized_khabar,
                khabar_embedding=khabar_embedding,
                note=self._origin_village_note(origin_villages),
                # Category extraction remains message-scoped. These rollups
                # intentionally retain the existing shared behavior until
                # category details can be attributed to individual villages.
                total_deaths=total_deaths,
                total_injuries=total_injuries,
                deaths=village_deaths,
                injuries=village_injuries,
                exact_hash=exact_hash,
                duplicate_flag=duplicate_flag,
                duplicate_level=duplicate_level,
                duplicate_similarity_score=duplicate_score,
                verification_status=verification_status,
                verification_reason=_verification_reason(
                    representative.match_result,
                    duplicate_flag=duplicate_flag,
                    duplicate_level=duplicate_level,
                    duplicate_similarity_score=duplicate_score,
                )
                if verification_status == "needs_verification"
                else None,
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
                        male_d=casualties.male_deaths,
                        male_i=casualties.male_injuries,
                        female_d=casualties.female_deaths,
                        female_i=casualties.female_injuries,
                        children_d=casualties.children_deaths,
                        children_i=casualties.children_injuries,
                        **mapped_fields,
                    )
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
            "village_match_status": match_result.get("village_match_status", "unmatched"),
            "village_review_required": match_result.get("village_review_required", True),
            "raw_village_text": match_result.get("raw_village_text"),
            "village_role": match_result.get("village_role", VillageRole.target.value),
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

    @staticmethod
    def _root_casualties_for_village(
        village_match: dict[str, Any],
        casualties: ExtractionCasualties,
        *,
        is_multi_village: bool,
    ) -> tuple[int | None, int | None]:
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
            return deaths, injuries
        return (
            deaths if deaths is not None else casualties.deaths,
            injuries if injuries is not None else casualties.injuries,
        )

    @staticmethod
    def _materializes_village_match(village_match: dict[str, Any]) -> bool:
        return village_match.get("village_role", VillageRole.target.value) == VillageRole.target.value

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

    @staticmethod
    def _origin_village_note(origin_villages: list[str]) -> str | None:
        if not origin_villages:
            return None
        if len(origin_villages) == 1:
            return f"Origin village: {origin_villages[0]}"
        joined = ", ".join(origin_villages)
        return f"Origin villages: {joined}"

    @staticmethod
    def _build_exact_hash(
        khabar: str,
        village_id: int,
        condition_id: int,
        event_date: str,
    ) -> str:
        normalized = " ".join(khabar.split())
        key = f"{normalized}|{village_id}|{condition_id}|{event_date}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    @staticmethod
    def _is_exact_hash_conflict(exc: IntegrityError) -> bool:
        diagnostic = getattr(exc.orig, "diag", None)
        constraint_name = getattr(diagnostic, "constraint_name", None)
        return constraint_name == EXACT_HASH_CONSTRAINT
