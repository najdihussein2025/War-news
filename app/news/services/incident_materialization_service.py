from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.llm.dtos import ExtractionResult
from app.news.models import Incident, IncidentDetail, RawMessage

logger = logging.getLogger(__name__)

ELIGIBLE_MATCH_STATUSES = frozenset({"matched", "matched_low_confidence"})
EXACT_HASH_CONSTRAINT = "uq_incidents_exact_hash_active"


@dataclass
class MaterializationStats:
    inserted: int = 0
    skipped_ineligible: int = 0
    skipped_duplicate_hash: int = 0


class IncidentMaterializationService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.stats = MaterializationStats()

    def materialize(self, representative: RawMessage) -> Incident | None:
        ineligible_reason = self._ineligible_reason(representative.match_result)
        if ineligible_reason is not None:
            self.stats.skipped_ineligible += 1
            logger.info(
                "raw_message_id=%s skipped: %s",
                representative.id,
                ineligible_reason,
            )
            return None

        if representative.extraction_result is None:
            raise ValueError(
                f"raw_message id={representative.id} has no extraction_result"
            )
        extraction = ExtractionResult.model_validate(
            representative.extraction_result
        )

        event_datetime = representative.message_datetime
        if event_datetime is None:
            raise ValueError(
                f"raw_message id={representative.id} has no message_datetime"
            )

        match_result = representative.match_result or {}
        village_id = self._required_int(match_result, "matched_village_id")
        condition_id = self._required_int(match_result, "matched_condition_id")
        exact_hash = self._build_exact_hash(
            khabar=representative.raw_text or "",
            village_id=village_id,
            condition_id=condition_id,
            event_date=event_datetime.date().isoformat(),
        )
        casualties = extraction.casualties

        incident = Incident(
            raw_message_id=representative.id,
            village_id=village_id,
            condition_id=condition_id,
            source_id=representative.source_id,
            event_date=event_datetime.date(),
            event_time=event_datetime.time(),
            khabar=representative.raw_text or "",
            khabar_embedding=representative.content_embedding,
            total_deaths=casualties.total_deaths,
            total_injuries=casualties.total_injuries,
            deaths=casualties.deaths,
            injuries=casualties.injuries,
            exact_hash=exact_hash,
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
            self.db.commit()
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
                "raw_message_id=%s existing_incident_id=%s",
                representative.id,
                existing_id,
            )
            return None
        except Exception:
            self.db.rollback()
            raise

        self.stats.inserted += 1
        return incident

    @staticmethod
    def _ineligible_reason(match_result: dict[str, Any] | None) -> str | None:
        if not match_result:
            return "match_result is missing"

        village_status = match_result.get("village_match_status")
        if village_status not in ELIGIBLE_MATCH_STATUSES:
            return f"village_match_status={village_status!r} is ineligible"

        condition_status = match_result.get("condition_match_status")
        if condition_status not in ELIGIBLE_MATCH_STATUSES:
            return f"condition_match_status={condition_status!r} is ineligible"

        if IncidentMaterializationService._optional_int(
            match_result.get("matched_village_id")
        ) is None:
            return "matched_village_id is missing"

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
