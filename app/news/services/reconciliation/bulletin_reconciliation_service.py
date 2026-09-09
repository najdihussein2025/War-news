from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.llm.dtos import CasualtyScope, ExtractionResult
from app.news.models import Incident, IncidentUpdate, RawMessage, UpdateAction
from app.news.models.bulletin_casualty_group import BulletinCasualtyGroup
from app.news.repositories.bulletin_casualty_group_repository import (
    BulletinCasualtyGroupRepository,
)
from app.news.services.clustering.clustering_service import (
    village_ids_from_match_result,
)
from app.news.services.incident_details.casualty_scope_backstop import (
    validate_casualty_scope,
)

logger = logging.getLogger(__name__)


class BulletinReconciliationService:
    def __init__(
        self,
        db: Session,
        *,
        groups: BulletinCasualtyGroupRepository | None = None,
    ) -> None:
        self.db = db
        self.groups = groups or BulletinCasualtyGroupRepository(db)

    def run_once(self, *, as_of: datetime | None = None) -> dict[str, int]:
        now = as_of or datetime.now(timezone.utc)
        summary = {
            "processed": 0,
            "succeeded": 0,
            "failed": 0,
            "expired": 0,
            "resolved": 0,
            "pending": 0,
        }

        expiring_ids = [group.id for group in self.groups.list_expiring_groups(now)]
        for group_id in expiring_ids:
            summary["processed"] += 1
            try:
                group = self.db.get(BulletinCasualtyGroup, group_id)
                if group is None or group.breakdown_status.value != "pending":
                    summary["succeeded"] += 1
                    continue
                self.groups.mark_expired(group, expired_at=now)
                self.db.commit()
                summary["succeeded"] += 1
                summary["expired"] += 1
            except Exception:
                self.db.rollback()
                summary["failed"] += 1
                logger.exception("Failed to expire bulletin casualty group id=%s", group_id)

        open_ids = [group.id for group in self.groups.list_open_groups(now)]
        for group_id in open_ids:
            summary["processed"] += 1
            try:
                group = self.db.get(BulletinCasualtyGroup, group_id)
                if group is None or group.breakdown_status.value != "pending":
                    summary["succeeded"] += 1
                    continue
                candidate = self._find_candidate(group)
                if candidate is None:
                    summary["pending"] += 1
                    summary["succeeded"] += 1
                    continue
                self._apply_candidate(group, candidate, resolved_at=now)
                self.db.commit()
                summary["resolved"] += 1
                summary["succeeded"] += 1
            except Exception:
                self.db.rollback()
                summary["failed"] += 1
                logger.exception(
                    "Failed to reconcile bulletin casualty group id=%s",
                    group_id,
                )

        return summary

    def _find_candidate(
        self,
        group: BulletinCasualtyGroup,
    ) -> RawMessage | None:
        origin = self.db.get(RawMessage, group.raw_message_id)
        if origin is None or origin.message_datetime is None:
            return None
        window = timedelta(hours=settings.bulletin_reconciliation_window_hours)
        candidates = self.db.scalars(
            select(RawMessage)
            .where(
                RawMessage.id != origin.id,
                RawMessage.message_datetime >= origin.message_datetime - window,
                RawMessage.message_datetime <= origin.message_datetime + window,
                RawMessage.extraction_result.is_not(None),
            )
            .order_by(RawMessage.message_datetime.asc(), RawMessage.id.asc())
        ).all()
        group_ids = {
            village_id
            for village_id in group.village_ids
            if isinstance(village_id, int) and not isinstance(village_id, bool)
        }
        if not group_ids:
            return None

        for candidate in candidates:
            extraction = ExtractionResult.model_validate(candidate.extraction_result)
            if extraction.casualty_scope != CasualtyScope.per_village_exact:
                continue
            validation = validate_casualty_scope(
                casualty_scope=extraction.casualty_scope,
                evidence=extraction.casualty_scope_evidence,
                village_roles=list(extraction.village_roles),
            )
            if not validation.plausible:
                continue
            candidate_ids = self._target_village_ids(candidate.match_result)
            overlap = len(group_ids & candidate_ids) / len(group_ids)
            if overlap < settings.bulletin_reconciliation_village_set_min_overlap:
                continue
            if self._exact_counts(candidate, group_ids):
                return candidate
        return None

    def _apply_candidate(
        self,
        group: BulletinCasualtyGroup,
        candidate: RawMessage,
        *,
        resolved_at: datetime,
    ) -> None:
        group_ids = {
            village_id
            for village_id in group.village_ids
            if isinstance(village_id, int) and not isinstance(village_id, bool)
        }
        exact_counts = self._exact_counts(candidate, group_ids)
        incidents = self.db.scalars(
            select(Incident).where(
                Incident.raw_message_id == group.raw_message_id,
                Incident.village_id.in_(exact_counts),
                Incident.is_deleted.is_(False),
            )
        ).all()
        for incident in incidents:
            if self._already_applied(incident, group, candidate):
                continue
            deaths, injuries = exact_counts[incident.village_id]
            old_values = {
                "deaths": incident.deaths,
                "injuries": incident.injuries,
            }
            if deaths is not None:
                incident.deaths = deaths
            if injuries is not None:
                incident.injuries = injuries
            self.db.add(incident)
            self.db.add(
                IncidentUpdate(
                    incident_id=incident.id,
                    action=UpdateAction.pipeline_merge,
                    old_values=old_values,
                    new_values={
                        "deaths": incident.deaths,
                        "injuries": incident.injuries,
                        "bulletin_group_id": group.id,
                        "resolved_by_raw_message_id": candidate.id,
                    },
                    performed_by=None,
                )
            )
        self.groups.mark_resolved(
            group,
            resolved_at=resolved_at,
            resolved_by_raw_message_id=candidate.id,
        )

    def _already_applied(
        self,
        incident: Incident,
        group: BulletinCasualtyGroup,
        candidate: RawMessage,
    ) -> bool:
        updates = self.db.scalars(
            select(IncidentUpdate).where(
                IncidentUpdate.incident_id == incident.id,
                IncidentUpdate.action == UpdateAction.pipeline_merge,
            )
        ).all()
        return any(
            isinstance(update.new_values, dict)
            and update.new_values.get("bulletin_group_id") == group.id
            and update.new_values.get("resolved_by_raw_message_id") == candidate.id
            for update in updates
        )

    @staticmethod
    def _target_village_ids(match_result: dict[str, Any] | None) -> frozenset[int]:
        if not match_result:
            return frozenset()
        matches = match_result.get("village_matches")
        if not isinstance(matches, list):
            return village_ids_from_match_result(match_result)
        target_result = {
            "village_matches": [
                item
                for item in matches
                if isinstance(item, dict)
                and item.get("village_role", "target") == "target"
            ]
        }
        return village_ids_from_match_result(target_result)

    @staticmethod
    def _exact_counts(
        candidate: RawMessage,
        group_ids: set[int],
    ) -> dict[int, tuple[int | None, int | None]]:
        match_result = candidate.match_result or {}
        matches = match_result.get("village_matches")
        if not isinstance(matches, list):
            return {}
        exact: dict[int, tuple[int | None, int | None]] = {}
        for item in matches:
            if not isinstance(item, dict) or item.get("village_role", "target") != "target":
                continue
            village_id = item.get("matched_village_id")
            if (
                not isinstance(village_id, int)
                or isinstance(village_id, bool)
                or village_id not in group_ids
            ):
                continue
            deaths = item.get("deaths")
            injuries = item.get("injuries")
            deaths = deaths if isinstance(deaths, int) and not isinstance(deaths, bool) else None
            injuries = (
                injuries
                if isinstance(injuries, int) and not isinstance(injuries, bool)
                else None
            )
            if deaths is not None or injuries is not None:
                exact[village_id] = (deaths, injuries)
        return exact
