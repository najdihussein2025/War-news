from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.llm.dtos import ExtractionResult
from app.news.interfaces import DedupMatchingInterface
from app.news.models import Incident, IncidentDetail, RawMessage
from app.news.services.category_mapper import compute_rollups, map_categories

logger = logging.getLogger(__name__)

ELIGIBLE_MATCH_STATUSES = frozenset({"matched", "matched_low_confidence"})
AIR_VIOLATION_CONDITION_IDS = frozenset({35, 36, 38})
EXACT_HASH_CONSTRAINT = "uq_incidents_exact_hash_active"


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

    def materialize(self, representative: RawMessage) -> list[Incident]:
        """Create one Incident per eligible village_match entry.

        Returns a list of successfully inserted (or merged) Incidents (may be
        empty). Ineligible or skipped villages are counted in stats but do not
        abort processing for other villages on the same message.
        """
        match_result = self._normalize_match_result(representative.match_result)
        if match_result is None:
            self.stats.skipped_ineligible += 1
            logger.info(
                "raw_message_id=%s skipped: match_result is missing",
                representative.id,
            )
            return []

        condition_ineligible = self._condition_ineligible_reason(match_result)
        if condition_ineligible is not None:
            self.stats.skipped_ineligible += 1
            logger.info(
                "raw_message_id=%s skipped: %s",
                representative.id,
                condition_ineligible,
            )
            return []

        condition_id = self._required_int(match_result, "matched_condition_id")

        if condition_id in AIR_VIOLATION_CONDITION_IDS:
            self.stats.skipped_air_violation_routed += 1
            logger.info(
                "raw_message_id=%s skipped: routed to air_violations, condition_id=%s",
                representative.id,
                condition_id,
            )
            return []

        if representative.extraction_result is None:
            raise ValueError(
                f"raw_message id={representative.id} has no extraction_result"
            )
        extraction = ExtractionResult.model_validate(representative.extraction_result)

        event_datetime = representative.message_datetime
        if event_datetime is None:
            raise ValueError(
                f"raw_message id={representative.id} has no message_datetime"
            )

        casualties = extraction.casualties
        mapped_fields = map_categories(extraction.categories)
        total_deaths, total_injuries = compute_rollups(mapped_fields, casualties)
        created: list[Incident] = []

        village_matches: list[dict[str, Any]] = match_result.get("village_matches", [])
        if not village_matches:
            self.stats.skipped_ineligible += 1
            logger.info(
                "raw_message_id=%s skipped: village_matches is empty",
                representative.id,
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

            exact_hash = self._build_exact_hash(
                khabar=representative.raw_text or "",
                village_id=village_id,
                condition_id=condition_id,
                event_date=event_datetime.date().isoformat(),
            )

            # Dedup check: merge into an existing similar incident instead of
            # inserting a new one, if the dedup service is configured.
            khabar_embedding = representative.content_embedding
            duplicate_flag = False
            if self.dedup_service is not None and khabar_embedding is not None:
                existing, score = self.dedup_service.find_best_match(
                    village_id=village_id,
                    condition_id=condition_id,
                    event_date=event_datetime.date(),
                    khabar_embedding=khabar_embedding,
                )
                if existing is not None and score >= settings.dedup_high_threshold:
                    try:
                        self.dedup_service.merge_into_incident(
                            existing=existing,
                            new_candidate_data={
                                "deaths": casualties.deaths,
                                "injuries": casualties.injuries,
                                "khabar": representative.raw_text or "",
                            },
                            raw_message_id=representative.id,
                        )
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
                    logger.info(
                        "raw_message_id=%s village_id=%s dedup_flag: score=%.3f "
                        "possible_duplicate_of_incident_id=%s",
                        representative.id,
                        village_id,
                        score,
                        existing.id,
                    )

            incident = Incident(
                raw_message_id=representative.id,
                village_id=village_id,
                condition_id=condition_id,
                source_id=representative.source_id,
                event_date=event_datetime.date(),
                event_time=event_datetime.time(),
                khabar=representative.raw_text or "",
                khabar_embedding=khabar_embedding,
                total_deaths=total_deaths,
                total_injuries=total_injuries,
                deaths=casualties.deaths,
                injuries=casualties.injuries,
                exact_hash=exact_hash,
                duplicate_flag=duplicate_flag,
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
                        **mapped_fields,
                    )
                )
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
    def _condition_ineligible_reason(match_result: dict[str, Any]) -> str | None:
        condition_status = match_result.get("condition_match_status")
        if condition_status not in ELIGIBLE_MATCH_STATUSES:
            return f"condition_match_status={condition_status!r} is ineligible"
        if IncidentMaterializationService._optional_int(
            match_result.get("matched_condition_id")
        ) is None:
            return "matched_condition_id is missing"
        return None

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
