from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.text_sanitizer import strip_emoji_and_pictographs
from app.llm.dtos import ExtractionResult
from app.news.interfaces import DedupMatchingInterface
from app.news.models import Incident, IncidentDetail, MatchStatus, MessageStatus, RawMessage
from app.news.services.category_mapper import compute_rollups, map_categories
from app.news.services.fast_path_dedup import (
    MATERIALIZE_MATCH_STATUSES,
    FastPathDedupOutcome,
    FastPathDedupService,
)
from app.news.services.pipeline_advisory_lock import acquire_fast_path_village_lock
from app.news.services.fast_path_eligibility import (
    ELIGIBLE_MATCH_STATUSES,
    ERROR_AIR_VIOLATION,
    ERROR_EXACT_HASH,
    ERROR_NO_VILLAGE,
    ERROR_UNMATERIALIZABLE,
    permanent_ineligibility_reason,
)


def _initial_verification_status(match_result: dict | None) -> str:
    result = match_result or {}
    if result.get("condition_match_status") != "matched":
        return "needs_verification"
    villages = result.get("village_matches") or []
    if any(v.get("village_match_status") != "matched" for v in villages):
        return "needs_verification"
    return "auto_processed"

logger = logging.getLogger(__name__)
BEIRUT_TIMEZONE = ZoneInfo("Asia/Beirut")


def _incident_event_datetime(value: datetime) -> datetime:
    """Return the source timestamp in the project's local calendar/time."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(BEIRUT_TIMEZONE)

EXACT_HASH_CONSTRAINT = "uq_incidents_exact_hash_active"


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
    ) -> None:
        self.db = db
        self.dedup_service = dedup_service
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

        created: list[Incident] = []
        confident_duplicate_villages = 0
        materializable_villages = 0
        representative_raw_message_id: int | None = None

        for village_match in village_matches:
            village_status = village_match.get("village_match_status")
            village_id = self._optional_int(village_match.get("matched_village_id"))
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

            if decision.outcome == FastPathDedupOutcome.confident_duplicate:
                canonical_incident = decision.canonical_incident
                if decision.representative_raw_message_id is not None:
                    representative_raw_message_id = decision.representative_raw_message_id

                khabar_embedding = representative.content_embedding
                if (
                    self.dedup_service is not None
                    and khabar_embedding is not None
                    and village_id is not None
                    and canonical_incident is not None
                ):
                    existing, score = self.dedup_service.find_best_match(
                        village_id=village_id,
                        condition_id=condition_id,
                        event_date=event_datetime.date(),
                        khabar_embedding=khabar_embedding,
                        exclude_raw_message_id=representative.id,
                    )
                    merge_target = existing or canonical_incident
                    mapped_fields = map_categories(extraction.categories)
                    casualties = extraction.casualties
                    total_deaths, total_injuries = compute_rollups(
                        mapped_fields,
                        casualties,
                    )

                    if score >= settings.dedup_high_threshold:
                        try:
                            self.dedup_service.merge_into_incident(
                                existing=merge_target,
                                new_candidate_data={
                                    "deaths": casualties.deaths,
                                    "injuries": casualties.injuries,
                                    "total_deaths": total_deaths,
                                    "total_injuries": total_injuries,
                                    "khabar": representative.raw_text or "",
                                    "mapped_fields": mapped_fields,
                                },
                                raw_message_id=representative.id,
                            )
                            fast_dedup.incidents.create_fast_path_duplicate_match(
                                canonical_incident=merge_target,
                                raw_message_id=representative.id,
                                status=MatchStatus.confirmed_duplicate,
                                similarity_score=score,
                            )
                            self._mark_materialized(representative, fast_path=True)
                            self.db.commit()
                            created.append(merge_target)
                            logger.info(
                                "raw_message_id=%s village_id=%s fast_path merged into "
                                "incident_id=%s score=%.3f",
                                representative.id,
                                village_id,
                                merge_target.id,
                                score,
                            )
                        except Exception:
                            self.db.rollback()
                            raise
                        if holds_village_lock:
                            self.db.commit()
                        continue

                    try:
                        fast_dedup.incidents.create_fast_path_duplicate_match(
                            canonical_incident=merge_target,
                            raw_message_id=representative.id,
                            status=MatchStatus.insufficient_score,
                            similarity_score=score,
                        )
                        self.db.commit()
                    except Exception:
                        self.db.rollback()
                        raise

                    incident = self._insert_fast_incident(
                        representative=representative,
                        extraction=extraction,
                        village_id=village_id,
                        condition_id=condition_id,
                        event_datetime=event_datetime,
                        duplicate_flag=score >= settings.dedup_low_threshold,
                    )
                    if incident is not None:
                        created.append(incident)
                    logger.info(
                        "raw_message_id=%s village_id=%s fast_path insufficient_score "
                        "score=%.3f duplicate_flag=%s incident_id=%s",
                        representative.id,
                        village_id,
                        score,
                        score >= settings.dedup_low_threshold,
                        incident.id if incident is not None else None,
                    )
                    if holds_village_lock:
                        self.db.commit()
                    continue

                confident_duplicate_villages += 1
                self.fast_stats.skipped_confident_duplicate += 1
                try:
                    if canonical_incident is not None:
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
                    "duplicate_match_written=%s (no embedding score)",
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
            )
            if incident is not None:
                created.append(incident)

        if (
            materializable_villages > 0
            and confident_duplicate_villages == materializable_villages
            and not created
            and representative_raw_message_id is not None
        ):
            representative.status = MessageStatus.duplicate
            representative.duplicate_of_id = representative_raw_message_id
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
        duplicate_flag: bool = False,
    ) -> Incident | None:
        if village_id is None:
            self.fast_stats.skipped_ineligible += 1
            return None

        casualties = extraction.casualties
        total_deaths, total_injuries = compute_rollups({}, casualties)
        sanitized_khabar = strip_emoji_and_pictographs(representative.raw_text or "")

        exact_hash = self._build_exact_hash(
            khabar=sanitized_khabar,
            village_id=village_id,
            condition_id=condition_id,
            event_date=event_datetime.date().isoformat(),
        )

        incident = Incident(
            raw_message_id=representative.id,
            village_id=village_id,
            condition_id=condition_id,
            source_id=representative.source_id,
            event_date=event_datetime.date(),
            event_time=event_datetime.time(),
            khabar=sanitized_khabar,
            khabar_embedding=None,
            total_deaths=total_deaths,
            total_injuries=total_injuries,
            deaths=casualties.deaths,
            injuries=casualties.injuries,
            exact_hash=exact_hash,
            duplicate_flag=duplicate_flag,
            details_pending=True,
            verification_status=_initial_verification_status(representative.match_result),
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
        mapped_fields = map_categories(extraction.categories)
        total_deaths, total_injuries = compute_rollups(mapped_fields, casualties)
        created: list[Incident] = []

        village_matches: list[dict[str, Any]] = match_result.get("village_matches", [])
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
            village_status = village_match.get("village_match_status")
            village_id = self._optional_int(village_match.get("matched_village_id"))

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

            sanitized_khabar = strip_emoji_and_pictographs(
                representative.raw_text or ""
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
                )
                if existing is not None and score >= settings.dedup_high_threshold:
                    try:
                        existing.duplicate_level = "high"
                        existing.duplicate_similarity_score = score
                        self.dedup_service.merge_into_incident(
                            existing=existing,
                            new_candidate_data={
                                "deaths": casualties.deaths,
                                "injuries": casualties.injuries,
                                "total_deaths": total_deaths,
                                "total_injuries": total_injuries,
                                "khabar": representative.raw_text or "",
                                "mapped_fields": mapped_fields,
                            },
                            raw_message_id=representative.id,
                        )
                        self._mark_materialized(representative, fast_path=False)
                        self.db.commit()
                        self.stats.merged_into_existing += 1
                        logger.info(
                            "raw_message_id=%s village_id=%s merged into "
                            "incident_id=%s score=%.3f",
                            representative.id,
                            village_id,
                            existing.id,
                            score,
                        )
                        created.append(existing)
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

            incident = Incident(
                raw_message_id=representative.id,
                village_id=village_id,
                condition_id=condition_id,
                source_id=representative.source_id,
                event_date=event_datetime.date(),
                event_time=event_datetime.time(),
                khabar=sanitized_khabar,
                khabar_embedding=khabar_embedding,
                total_deaths=total_deaths,
                total_injuries=total_injuries,
                deaths=casualties.deaths,
                injuries=casualties.injuries,
                exact_hash=exact_hash,
                duplicate_flag=duplicate_flag,
                duplicate_level=duplicate_level,
                duplicate_similarity_score=duplicate_score,
                verification_status=_initial_verification_status(representative.match_result),
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
