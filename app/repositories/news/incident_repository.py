import hashlib
from contextlib import AbstractContextManager
from datetime import date, timedelta
from typing import Any

from sqlalchemy import and_, desc, select
from sqlalchemy.orm import Session

from app.dtos.news import ExtractedCandidate
from app.interfaces.news import IncidentRepositoryInterface
from app.models.news import (
    DuplicateMatch,
    Incident,
    IncidentDetail,
    IncidentUpdate,
    MatchStatus,
    MatchType,
    RawMessage,
    UpdateAction,
)

class IncidentRepository(IncidentRepositoryInterface):
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_duplicate_candidates(
        self,
        village_id: int,
        event_date: date,
        khabar_embedding: list[float],
        window_days: int,
    ) -> list[tuple[Incident, float]]:
        start_date = event_date - timedelta(days=window_days)
        end_date = event_date + timedelta(days=window_days)
        embedding_similarity = (
            1.0 - Incident.khabar_embedding.cosine_distance(khabar_embedding)
        ).label("embedding_similarity")

        rows = self.db.execute(
            select(Incident, embedding_similarity)
            .where(
                and_(
                    Incident.village_id == village_id,
                    Incident.is_deleted.is_(False),
                    Incident.event_date >= start_date,
                    Incident.event_date <= end_date,
                    Incident.khabar_embedding.is_not(None),
                )
            )
            .order_by(desc(embedding_similarity))
        ).all()

        return [
            (incident, float(embedding_score or 0.0))
            for incident, embedding_score in rows
        ]

    def create_with_detail(
        self,
        message: RawMessage,
        candidate: ExtractedCandidate,
        village_id: int,
        condition_id: int,
        khabar_embedding: list[float],
        duplicate_flag: bool = False,
    ) -> Incident:
        event_datetime = message.message_datetime
        if event_datetime is None:
            raise RuntimeError(
                "raw_message.message_datetime is required for incident creation."
            )

        exact_hash = self._build_exact_hash(
            khabar=message.raw_text or "",
            village_id=village_id,
            condition_id=condition_id,
            event_date=event_datetime.date().isoformat(),
        )

        incident = Incident(
            village_id=village_id,
            condition_id=condition_id,
            source_id=message.source_id,
            raw_message_id=message.id,
            event_date=event_datetime.date(),
            event_time=event_datetime.time(),
            khabar=message.raw_text or "",
            khabar_embedding=khabar_embedding,
            deaths=candidate.deaths,
            injuries=candidate.injuries,
            exact_hash=exact_hash,
            duplicate_flag=duplicate_flag,
            created_by=None,
        )
        self.db.add(incident)
        self.db.flush()
        self.db.add(
            IncidentDetail(
                incident_id=incident.id,
                male_d=candidate.male_d,
                male_i=candidate.male_i,
                female_d=candidate.female_d,
                female_i=candidate.female_i,
                children_d=candidate.children_d,
                children_i=candidate.children_i,
            )
        )
        self.db.flush()
        return incident

    def create_duplicate_match(
        self,
        incident: Incident,
        matched_incident: Incident,
        similarity_score: float,
    ) -> None:
        self.db.add(
            DuplicateMatch(
                incident_id=incident.id,
                matched_incident_id=matched_incident.id,
                match_type=MatchType.soft,
                similarity_score=similarity_score,
                status=MatchStatus.pending,
            )
        )
        self.db.flush()

    def merge_existing(
        self,
        existing: Incident,
        new_candidate_data: dict[str, Any],
        raw_message_id: int,
    ) -> None:
        old_values = self._snapshot_merge_fields(existing)

        existing.deaths = self._max_preserving_empty(
            existing.deaths,
            new_candidate_data.get("deaths"),
        )
        existing.total_deaths = self._max_preserving_empty(
            existing.total_deaths,
            new_candidate_data.get("deaths"),
        )
        existing.injuries = self._max_preserving_empty(
            existing.injuries,
            new_candidate_data.get("injuries"),
        )
        existing.total_injuries = self._max_preserving_empty(
            existing.total_injuries,
            new_candidate_data.get("injuries"),
        )

        khabar = new_candidate_data.get("khabar")
        if khabar:
            existing.note = self._append_note(existing.note, khabar, raw_message_id)

        new_values = self._snapshot_merge_fields(existing)
        if old_values != new_values:
            self.db.add(
                IncidentUpdate(
                    incident_id=existing.id,
                    action=UpdateAction.edit,
                    old_values=old_values,
                    new_values=new_values,
                    performed_by=None,
                )
            )
        self.db.add(existing)

    def begin_nested(self) -> AbstractContextManager[object]:
        return self.db.begin_nested()

    def rollback(self) -> None:
        self.db.rollback()

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
    def _max_preserving_empty(current: int | None, incoming: Any) -> int | None:
        incoming_value = incoming if isinstance(incoming, int) else None
        if current is None and incoming_value is None:
            return None
        return max(current or 0, incoming_value or 0)

    @staticmethod
    def _append_note(existing_note: str | None, khabar: str, raw_message_id: int) -> str:
        appended = (
            f"Automated duplicate merge from raw_message_id={raw_message_id}:\n{khabar}"
        )
        if not existing_note:
            return appended
        return f"{existing_note}\n\n{appended}"

    @staticmethod
    def _snapshot_merge_fields(incident: Incident) -> dict[str, Any]:
        return {
            "deaths": incident.deaths,
            "total_deaths": incident.total_deaths,
            "injuries": incident.injuries,
            "total_injuries": incident.total_injuries,
            "note": incident.note,
        }
