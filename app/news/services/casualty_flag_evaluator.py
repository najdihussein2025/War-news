from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.news.models import Incident, IncidentUpdate, RawMessage
from app.news.services.materialization.verification_signals import count_missing_reason, natural_casualty_total, shared_toll_member_reason, shared_toll_owner_reason

logger = logging.getLogger(__name__)


class CasualtyFlagEvaluator:
    """Evaluate deterministic stored casualty status; never invokes an LLM."""

    def __init__(self, db: Session, *, enabled: bool | None = None) -> None:
        from app.news.repositories.incident_verification_flag_repository import IncidentVerificationFlagRepository

        self.db = db
        self.repository = IncidentVerificationFlagRepository(db)
        self.enabled = settings.casualty_flags_enabled if enabled is None else enabled

    def evaluate_incident(self, incident_id: UUID) -> dict[str, int]:
        from app.news.repositories.incident_verification_flag_repository import IncidentVerificationFlagRepository

        result ={"opened": 0, "updated": 0, "auto_cleared": 0, "skipped": 0}
        if not self.enabled:
            result["skipped"] += 1
            return result
        incident = self.db.get(Incident, incident_id)
        if incident is None:
            result["skipped"] += 1
            return result
        open_by_reason = {
            flag.reason_code: flag
            for flag in self.repository.list_open_for_incident(incident_id)
            if flag.flag_type == "casualty_check"
        }
        canonical_id = self._canonical_id(incident_id) if incident.is_deleted else None
        removed_reason = f"merged_into:{canonical_id}" if canonical_id else "incident_removed"
        if incident.is_deleted or incident.verification_status == "rejected":
            for flag in open_by_reason.values():
                self.repository.auto_clear(flag.id, removed_reason)
                result["auto_cleared"] += 1
            if canonical_id:
                nested = self.evaluate_incident(canonical_id)
                for key in result: result[key] += nested[key]
            return result
        if incident.verification_status == "verified" and self._has_admin_casualty_edit(incident_id):
            result["skipped"] += 1
            self._log(incident, "skipped_admin_edited", "all")
            return result

        wanted: dict[str, dict] = {}
        message_snapshot = self._message_snapshot(incident)
        missing = [
            kind for kind in ("deaths", "injuries")
            if getattr(incident, f"casualty_{kind}_status", None) == "count_missing"
        ]
        if missing:
            label = " and ".join(item.title() for item in missing)
            evidence = incident.casualty_status_evidence
            wanted["count_missing"] = {
                "affected_types": missing,
                "evidence_sentence": evidence,
                "known_exact_counts": {
                    kind: getattr(incident, kind)
                    for kind in ("deaths", "injuries") if kind not in missing
                },
                "summary": count_missing_reason(),
            }
        remaining = dict(incident.casualty_status_remaining_total or {})
        if incident.casualty_status == "aggregate_only" and any(
            isinstance(value, int) and value > 0 for value in remaining.values()
        ):
            siblings = self._siblings(incident)
            sibling_ids = [str(item.id) for item in siblings]
            existing_detail = getattr(open_by_reason.get("aggregate_no_breakdown"), "detail", None) or {}
            existing_totals = existing_detail.get("bulletin_totals") or {}
            # Keep the totals the flag opened with: admin entries written to the
            # sibling rows must not become the bulletin total they are checked against.
            totals = {
                kind: existing_totals[kind] if isinstance(existing_totals.get(kind), int)
                else self._bulletin_total(kind, siblings)
                for kind in ("deaths", "injuries")
            }
            known = [
                {"incident_id": str(item.id), "location": self._location_name(item),
                 "deaths": item.deaths, "injuries": item.injuries}
                for item in siblings if item.deaths is not None or item.injuries is not None
            ] or None
            wanted["aggregate_no_breakdown"] = {
                "bulletin_totals": totals,
                "locations_with_known_counts": known,
                "remaining_total": remaining,
                "sibling_incident_ids": sibling_ids,
                "source_message_id": incident.raw_message_id,
                "summary": self._aggregate_summary(totals, siblings, incident),
            }

        for reason, flag in open_by_reason.items():
            if reason not in wanted:
                self.repository.auto_clear(flag.id, "status_no_longer_matches")
                result["auto_cleared"] += 1
        visible_after = datetime.now(timezone.utc) + timedelta(
            minutes=settings.casualty_flag_grace_minutes
        )
        for reason, detail in wanted.items():
            if self.repository.has_previously_reviewed(incident_id, reason):
                result["skipped"] += 1
                self._log(incident, "skipped_previously_reviewed", reason)
                continue
            existing = open_by_reason.get(reason)
            if not message_snapshot and existing:
                existing_detail = getattr(existing, "detail", None) or {}
                message_snapshot = {
                    key: existing_detail.get(key)
                    for key in ("message_text", "message_datetime", "source_name")
                    if existing_detail.get(key) is not None
                }
            detail.update(message_snapshot)
            if existing and IncidentVerificationFlagRepository.is_unchanged(
                existing, severity="review", detail=detail,
                source_message_id=incident.raw_message_id, visible_after=existing.visible_after,
            ):
                self._log(incident, "unchanged", reason)
                continue
            self.repository.open_flag(
                incident_id=incident_id,
                flag_type="casualty_check",
                reason_code=reason,
                severity="review",
                detail=detail,
                source_message_id=incident.raw_message_id,
                visible_after=existing.visible_after if existing else visible_after,
            )
            result["updated" if existing else "opened"] += 1
            self._log(incident, "opened" if not existing else "updated", reason)
        return result

    def _message_snapshot(self, incident: Incident) -> dict:
        if incident.raw_message_id is None:
            return {}
        message = self.db.get(RawMessage, incident.raw_message_id)
        if message is None:
            return {}
        text = (message.raw_text or "").strip()
        return {
            "message_text": text[:4000] or None,
            "message_datetime": message.message_datetime.isoformat() if message.message_datetime else None,
            "source_name": message.source_name,
        }

    def _siblings(self, incident: Incident) -> list[Incident]:
        if incident.raw_message_id is None: return [incident]
        return list(self.db.scalars(select(Incident).where(
            Incident.raw_message_id == incident.raw_message_id,
            Incident.is_deleted.is_(False),
        )).all())

    def _has_admin_casualty_edit(self, incident_id: UUID) -> bool:
        rows = self.db.execute(select(IncidentUpdate.new_values).where(
            IncidentUpdate.incident_id == incident_id,
            IncidentUpdate.performed_by.is_not(None),
        )).scalars()
        return any(any(key in (values or {}) for key in ("deaths", "injuries", "total_deaths", "total_injuries")) for values in rows)

    def _canonical_id(self, incident_id: UUID) -> UUID | None:
        rows = self.db.execute(select(IncidentUpdate.new_values).where(
            IncidentUpdate.incident_id == incident_id,
        ).order_by(IncidentUpdate.created_at.desc(), IncidentUpdate.id.desc())).scalars()
        for values in rows:
            value = (values or {}).get("canonical_incident_id")
            if value:
                try: return UUID(str(value))
                except ValueError: return None
        return None

    @staticmethod
    def _bulletin_total(kind: str, siblings: list[Incident]) -> int | None:
        """Toll from the stored status: unallocated remainder plus located exact counts."""
        remaining = [
            value for item in siblings
            if isinstance(value := (getattr(item, "casualty_status_remaining_total", None) or {}).get(kind), int)
        ]
        if not remaining:
            return max(
                (getattr(item, f"total_{kind}") for item in siblings if isinstance(getattr(item, f"total_{kind}"), int)),
                default=None,
            )
        located = sum(
            getattr(item, kind) for item in siblings
            if getattr(item, f"casualty_{kind}_status", None) == "exact" and isinstance(getattr(item, kind), int)
        )
        return max(remaining) + located

    @staticmethod
    def _location_name(item: Incident) -> str | None:
        return item.village_display_name or getattr(getattr(item, "village", None), "ref_name_en", None)

    @classmethod
    def _aggregate_summary(cls, totals: dict[str, int | None], siblings: list[Incident], incident: Incident) -> str:
        owner = siblings[0] if siblings else incident
        total = natural_casualty_total(totals.get("deaths"), totals.get("injuries"))
        if incident.id == owner.id:
            villages = "، ".join(cls._location_name(item) or "بلدة غير معروفة" for item in siblings)
            return shared_toll_owner_reason(total, villages)
        return shared_toll_member_reason(total, cls._location_name(owner) or "البلدة الأولى")

    @staticmethod
    def _log(incident: Incident, decision: str, reason: str) -> None:
        logger.info("casualty_flag decision=%s incident_id=%s message_id=%s reason_code=%s rule=stored_status",
                    decision, incident.id, incident.raw_message_id, reason)


def evaluate_casualty_flags_safely(db: Session, incident_id: UUID) -> None:
    if not settings.casualty_flags_enabled:
        return
    try:
        CasualtyFlagEvaluator(db).evaluate_incident(incident_id)
        db.flush()
    except Exception:
        logger.exception("casualty flag hook failed incident_id=%s", incident_id)
