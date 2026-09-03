from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID

from app.core.config import settings
from app.news.repositories.incident_repository import IncidentRepository

if TYPE_CHECKING:
    from app.news.models import Incident


class FastPathDedupOutcome(str, Enum):
    confident_duplicate = "confident_duplicate"
    materialize = "materialize"
    skip_ineligible = "skip_ineligible"


@dataclass(frozen=True)
class FastPathDedupDecision:
    outcome: FastPathDedupOutcome
    canonical_incident_id: UUID | None = None
    representative_raw_message_id: int | None = None
    canonical_incident: Incident | None = None


CONFIDENT_MATCH_STATUSES = frozenset({"matched"})
MATERIALIZE_MATCH_STATUSES = frozenset({"matched", "matched_low_confidence"})


class FastPathDedupService:
    def __init__(self, incident_repository: IncidentRepository) -> None:
        self.incidents = incident_repository

    def decide_for_village(
        self,
        *,
        village_match_status: str | None,
        condition_match_status: str | None,
        village_id: int | None,
        condition_id: int | None,
        message_datetime: datetime,
        exclude_raw_message_id: int | None = None,
    ) -> FastPathDedupDecision:
        if village_id is None or condition_id is None:
            return FastPathDedupDecision(outcome=FastPathDedupOutcome.skip_ineligible)

        if village_match_status not in MATERIALIZE_MATCH_STATUSES:
            return FastPathDedupDecision(outcome=FastPathDedupOutcome.skip_ineligible)
        if condition_match_status not in MATERIALIZE_MATCH_STATUSES:
            return FastPathDedupDecision(outcome=FastPathDedupOutcome.skip_ineligible)

        if (
            village_match_status in CONFIDENT_MATCH_STATUSES
            and condition_match_status in CONFIDENT_MATCH_STATUSES
        ):
            existing = self.incidents.find_active_incident_in_fast_dedup_window(
                village_id=village_id,
                condition_id=condition_id,
                message_datetime=message_datetime,
                window_days=settings.dedup_time_window_days,
                exclude_raw_message_id=exclude_raw_message_id,
            )
            if existing is not None:
                return FastPathDedupDecision(
                    outcome=FastPathDedupOutcome.confident_duplicate,
                    canonical_incident_id=existing.id,
                    representative_raw_message_id=existing.raw_message_id,
                    canonical_incident=existing,
                )

        return FastPathDedupDecision(outcome=FastPathDedupOutcome.materialize)
