import base64
import hashlib
import json
from contextlib import AbstractContextManager
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import and_, case, desc, false, func, or_, select, true, update as sa_update
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.text_sanitizer import strip_emoji_and_pictographs
from app.llm.dtos import ExtractedCandidate
from app.news.dtos import (
    CasualtyDemographicsDTO,
    DuplicateCandidateIncidentDTO,
    IncidentDetailDTO,
    IncidentDuplicateCandidateDTO,
    IncidentDuplicateResolutionResultDTO,
    IncidentCreateDTO,
    IncidentVillageDetailDTO,
    IncidentListItemDTO,
    IncidentListParams,
    IncidentListResponse,
    IncidentUpdateDTO,
)
from app.news.interfaces import IncidentRepositoryInterface
from app.news.models import (
    Condition,
    DuplicateMatch,
    Incident,
    IncidentDetail,
    IncidentUpdate,
    MatchStatus,
    MatchType,
    RawMessage,
    UpdateAction,
    Village,
)
from app.news.services.incident_detail_category_serializer import (
    serialize_incident_category_sections,
)
from app.news.services.incident_detail_edit_service import (
    IncidentDetailEditError,
    apply_incident_detail_edits,
)
from app.news.services.casualty_transition_merge import (
    apply_casualty_transitions,
    parse_casualty_transitions,
    sync_transition_totals,
)
from app.news.services.casualty_transition_backstop import (
    detect_casualty_transition_backstop,
)
from app.news.services.incident_detail_merge import merge_incident_detail_fields
from app.sources.models import Source, SourceType


class IncidentRepository(IncidentRepositoryInterface):
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_all(self, params: IncidentListParams) -> IncidentListResponse:
        filters = self._list_filters(params)
        low_confidence = self._low_confidence_match()
        event_datetime = func.coalesce(
            RawMessage.message_datetime,
            RawMessage.received_at,
        )
        event_date = func.coalesce(
            Incident.event_date,
            func.date(event_datetime),
        )
        created_at = func.coalesce(Incident.created_at, RawMessage.received_at)
        cursor = self._decode_list_cursor(params.cursor)

        base_query = (
            select(
                Incident.id.label("id"),
                RawMessage.id.label("raw_message_id"),
                RawMessage.status.label("raw_status"),
                func.coalesce(Village.ref_name_en, Village.cad_name).label("village"),
                Condition.action_en.label("condition"),
                event_date.label("event_date"),
                Incident.event_time,
                func.coalesce(
                    Incident.khabar,
                    func.left(RawMessage.raw_text, 300),
                ).label("khabar"),
                case(
                    (RawMessage.source_platform.is_not(None), func.initcap(RawMessage.source_platform)),
                    (RawMessage.external_message_id.ilike("twitter:%"), "Twitter"),
                    (RawMessage.external_message_id.ilike("telegram:%"), "Telegram"),
                    (RawMessage.external_message_id.ilike("facebook:%"), "Facebook"),
                    (Source.type == SourceType.telegram, "Telegram"),
                    (Source.type == SourceType.api, "API"),
                    (Source.type == SourceType.manual, "Manual"),
                    (Source.type == SourceType.twitter, "Twitter"),
                    (Source.type == SourceType.facebook, "Facebook"),
                    (Source.type == SourceType.website, "Website"),
                    else_=None,
                ).label("source"),
                self._source_reference_expression().label("source_reference"),
                case(
                    (Incident.id.is_(None), False),
                    (low_confidence, False),
                    else_=True,
                ).label("matched"),
                func.coalesce(
                    Incident.verification_status, "auto_processed"
                ).label("verification_status"),
                Incident.verification_reason,
                Incident.verified_by_user_id,
                Incident.verified_at,
                case(
                    (Incident.duplicate_flag.is_(True), "possible"),
                    else_="none",
                ).label("duplicate_flag"),
                Incident.duplicate_level,
                Incident.duplicate_similarity_score,
                func.coalesce(Incident.details_pending, true()).label(
                    "details_pending"
                ),
                created_at.label("created_at"),
                func.coalesce(Incident.version, 1).label("version"),
                Incident.locked_by_user_id,
                Incident.edit_lock_expires_at,
            )
            .select_from(Incident)
            .outerjoin(RawMessage, RawMessage.id == Incident.raw_message_id)
            .outerjoin(Village, Village.id == Incident.village_id)
            .outerjoin(Condition, Condition.id == Incident.condition_id)
            .outerjoin(Source, Source.id == Incident.source_id)
            .where(*filters)
        )
        if cursor is not None:
            base_query = base_query.where(
                self._list_cursor_filter(
                    params,
                    cursor,
                    created_at,
                    event_date,
                )
            )

        rows = self.db.execute(
            base_query.order_by(
                *self._list_ordering(params),
            )
            .limit(params.limit + 1)
        ).all()
        has_next_page = len(rows) > params.limit
        page_rows = rows[:params.limit]
        total = self.db.scalar(
            select(func.count(Incident.id))
            .select_from(Incident)
            .outerjoin(RawMessage, RawMessage.id == Incident.raw_message_id)
            .outerjoin(Village, Village.id == Incident.village_id)
            .outerjoin(Condition, Condition.id == Incident.condition_id)
            .outerjoin(Source, Source.id == Incident.source_id)
            .where(*filters)
        )
        latest_incident_at = self.db.scalar(
            select(
                func.max(
                    func.greatest(
                        created_at,
                        func.coalesce(Incident.updated_at, RawMessage.received_at),
                    )
                )
            )
            .select_from(Incident)
            .outerjoin(RawMessage, RawMessage.id == Incident.raw_message_id)
            .outerjoin(Village, Village.id == Incident.village_id)
            .outerjoin(Condition, Condition.id == Incident.condition_id)
            .outerjoin(Source, Source.id == Incident.source_id)
            .where(*filters)
        )
        summary = self.db.execute(
            select(
                func.count(Incident.id)
                .filter(func.coalesce(low_confidence, False).is_(True))
                .label("needs_verification_count"),
                func.count(Incident.id)
                .filter(Incident.duplicate_flag.is_(True))
                .label("duplicate_count"),
            )
            .select_from(Incident)
            .outerjoin(RawMessage, RawMessage.id == Incident.raw_message_id)
            .where(
                Incident.is_deleted.is_(False),
                or_(
                    RawMessage.id.is_(None),
                    ~RawMessage.raw_payload.op("?")("ocr_text"),
                ),
            )
        ).one()

        return IncidentListResponse(
            items=[
                IncidentListItemDTO.model_validate(
                    {
                        **row._mapping,
                        "khabar": strip_emoji_and_pictographs(
                            row._mapping["khabar"]
                        ).strip(),
                    }
                )
                for row in page_rows
            ],
            total=int(total or 0),
            limit=params.limit,
            next_cursor=(
                self._encode_list_cursor(page_rows[-1]._mapping)
                if has_next_page and page_rows
                else None
            ),
            latest_incident_at=latest_incident_at,
            needs_verification_count=int(summary.needs_verification_count or 0),
            duplicate_count=int(summary.duplicate_count or 0),
        )

    def get_by_id(self, incident_id: UUID) -> IncidentDetailDTO | None:
        low_confidence = self._low_confidence_match()
        row = self.db.execute(
            select(
                Incident,
                Village,
                func.coalesce(Village.ref_name_en, Village.cad_name).label("village"),
                Condition.action_en.label("condition"),
                case(
                    (Source.type == SourceType.telegram, "Telegram"),
                    (Source.type == SourceType.api, "API"),
                    (Source.type == SourceType.manual, "Manual"),
                    (Source.type == SourceType.twitter, "Twitter"),
                    (Source.type == SourceType.facebook, "Facebook"),
                    (Source.type == SourceType.website, "Website"),
                    else_=None,
                ).label("source"),
                self._source_reference_expression().label("source_reference"),
                case((low_confidence, False), else_=True).label("matched"),
                case(
                    (Incident.duplicate_flag.is_(True), "possible"),
                    else_="none",
                ).label("duplicate_flag"),
                IncidentDetail,
            )
            .outerjoin(Village, Village.id == Incident.village_id)
            .outerjoin(Condition, Condition.id == Incident.condition_id)
            .outerjoin(Source, Source.id == Incident.source_id)
            .outerjoin(RawMessage, RawMessage.id == Incident.raw_message_id)
            .outerjoin(IncidentDetail, IncidentDetail.incident_id == Incident.id)
            .where(
                Incident.id == incident_id,
                Incident.is_deleted.is_(False),
            )
        ).one_or_none()
        if row is None:
            return None

        incident = row.Incident
        detail = row.IncidentDetail
        village = row.Village
        values = {
            "id": incident.id,
            "village": row.village,
            "village_details": (
                IncidentVillageDetailDTO(
                    id=village.id,
                    acs_code=village.acs_code,
                    acs_name=village.acs_name,
                    cad_name=village.cad_name,
                    ref_name_en=village.ref_name_en,
                    ref_name_ar=village.ref_name_ar,
                    caza_en=village.caza_en,
                    caza_ar=village.caza_ar,
                    mohafaza_en=village.mohafaza_en,
                    mohafaza_ar=village.mohafaza_ar,
                    coord_x=village.coord_x,
                    coord_y=village.coord_y,
                )
                if village is not None
                else None
            ),
            "condition": row.condition,
            "source": row.source,
            "source_reference": row.source_reference,
            "khabar": strip_emoji_and_pictographs(incident.khabar).strip(),
            "note": self._sanitize_optional_text(incident.note),
            "moh": incident.moh,
            "martyrs": incident.martyrs,
            "worker_name": incident.worker_name,
            "source_link": incident.source_link,
            "source_link_2": incident.source_link_2,
            "total_deaths": incident.total_deaths,
            "total_injuries": incident.total_injuries,
            "deaths": incident.deaths,
            "injuries": incident.injuries,
            "event_date": incident.event_date,
            "event_time": incident.event_time,
            "created_at": incident.created_at,
            "version": incident.version,
            "locked_by_user_id": incident.locked_by_user_id,
            "edit_lock_expires_at": incident.edit_lock_expires_at,
            "matched": row.matched,
            "verification_status": incident.verification_status,
            "verification_reason": incident.verification_reason,
            "duplicate_flag": row.duplicate_flag,
            "duplicate_level": incident.duplicate_level,
            "duplicate_similarity_score": incident.duplicate_similarity_score,
            "casualty_demographics": CasualtyDemographicsDTO(
                male_d=detail.male_d if detail is not None else None,
                male_i=detail.male_i if detail is not None else None,
                female_d=detail.female_d if detail is not None else None,
                female_i=detail.female_i if detail is not None else None,
                children_d=detail.children_d if detail is not None else None,
                children_i=detail.children_i if detail is not None else None,
            ),
            **serialize_incident_category_sections(detail),
        }
        return IncidentDetailDTO.model_validate(values)

    def create_manual(self, payload: IncidentCreateDTO, created_by: UUID) -> IncidentDetailDTO:
        village_name = payload.village.strip()
        condition_name = payload.condition.strip()
        sanitized_khabar = strip_emoji_and_pictographs(payload.khabar).strip()
        sanitized_note = self._sanitize_optional_text(payload.note)
        sanitized_source_link = self._sanitize_optional_text(payload.source_link)
        village = self.db.scalar(
            select(Village).where(
                Village.is_active.is_(True),
                or_(
                    func.lower(Village.ref_name_en) == village_name.lower(),
                    func.lower(Village.cad_name) == village_name.lower(),
                    func.lower(Village.ref_name_ar) == village_name.lower(),
                ),
            )
        )
        if village is None:
            raise ValueError("Village was not found. Enter an existing village name.")
        condition = self.db.scalar(
            select(Condition).where(
                Condition.is_active.is_(True),
                or_(
                    func.lower(Condition.action_en) == condition_name.lower(),
                    func.lower(Condition.action_ar) == condition_name.lower(),
                ),
            )
        )
        if condition is None:
            raise ValueError("Condition was not found. Enter an existing condition name.")
        source = self._ensure_manual_source()
        incident = Incident(
            village_id=village.id,
            condition_id=condition.id,
            source_id=source.id,
            event_month=payload.event_date.strftime("%B"),
            event_date=payload.event_date,
            event_time=payload.event_time,
            khabar=sanitized_khabar,
            note=sanitized_note,
            source_link=sanitized_source_link,
            created_by=created_by,
        )
        self.db.add(incident)
        self.db.commit()
        detail = self.get_by_id(incident.id)
        if detail is None:
            raise RuntimeError("Created incident could not be loaded.")
        return detail

    def update(self, incident_id: UUID, payload: IncidentUpdateDTO, user_id: UUID) -> IncidentDetailDTO | None:
        incident = self.db.scalar(
            select(Incident).where(
                Incident.id == incident_id,
                Incident.is_deleted.is_(False),
                Incident.version == payload.version,
                Incident.locked_by_user_id == user_id,
            ).with_for_update()
        )
        if incident is None:
            self.db.rollback()
            if self.db.scalar(select(Incident.id).where(Incident.id == incident_id, Incident.is_deleted.is_(False))) is None:
                return None
            raise StaleDataError("Incident version or edit lock is stale.")
        text_fields = {
            "khabar",
            "note",
            "worker_name",
            "source_link",
            "source_link_2",
        }
        for field, value in payload.model_dump(exclude={"version"}).items():
            if field in text_fields:
                value = self._sanitize_optional_text(value)
                if field == "khabar" and value is None:
                    value = ""
            setattr(incident, field, value)
        incident.event_month = payload.event_date.strftime("%B")
        incident.locked_by_user_id = None
        incident.edit_lock_expires_at = None
        self.db.commit()
        return self.get_by_id(incident_id)

    def update_details(
        self,
        incident_id: UUID,
        fields: dict[str, Any],
        performed_by: UUID,
        version: int,
    ) -> IncidentDetailDTO | None:
        incident = self.db.scalar(
            select(Incident).where(
                Incident.id == incident_id,
                Incident.is_deleted.is_(False),
                Incident.version == version,
                Incident.locked_by_user_id == performed_by,
            ).with_for_update()
        )
        if incident is None:
            self.db.rollback()
            if self.db.scalar(select(Incident.id).where(Incident.id == incident_id, Incident.is_deleted.is_(False))) is None:
                return None
            raise StaleDataError("Incident version or edit lock is stale.")

        detail = self.db.scalar(
            select(IncidentDetail).where(IncidentDetail.incident_id == incident_id)
        )
        if detail is None:
            detail = IncidentDetail(incident_id=incident_id)
            self.db.add(detail)
            self.db.flush()

        try:
            old_values, new_values = apply_incident_detail_edits(
                incident,
                detail,
                fields,
            )
        except IncidentDetailEditError as exc:
            raise ValueError(str(exc)) from exc

        if old_values != new_values:
            self.db.add(
                IncidentUpdate(
                    incident_id=incident.id,
                    action=UpdateAction.edit,
                    old_values=old_values,
                    new_values=new_values,
                    performed_by=performed_by,
                )
            )

        self.db.add(detail)
        self.db.add(incident)
        incident.locked_by_user_id = None
        incident.edit_lock_expires_at = None
        self.db.commit()
        return self.get_by_id(incident_id)

    def delete(self, incident_id: UUID, version: int, user_id: UUID) -> bool:
        incident = self.db.scalar(
            select(Incident).where(
                Incident.id == incident_id,
                Incident.is_deleted.is_(False),
                Incident.version == version,
                Incident.locked_by_user_id == user_id,
            ).with_for_update()
        )
        if incident is None:
            self.db.rollback()
            if self.db.scalar(select(Incident.id).where(Incident.id == incident_id, Incident.is_deleted.is_(False))) is None:
                return False
            raise StaleDataError("Incident version or edit lock is stale.")
        incident.is_deleted = True
        self.db.commit()
        return True

    def acquire_edit_lock(self, incident_id: UUID, user_id: UUID) -> IncidentDetailDTO | None:
        now = datetime.now(timezone.utc)
        result = self.db.execute(
            sa_update(Incident)
            .where(
                Incident.id == incident_id,
                Incident.is_deleted.is_(False),
                (
                    Incident.locked_by_user_id.is_(None)
                    | (Incident.edit_lock_expires_at <= now)
                    | (Incident.locked_by_user_id == user_id)
                ),
            )
            .values(locked_by_user_id=user_id, edit_lock_expires_at=now + timedelta(minutes=5))
        )
        if result.rowcount == 0:
            self.db.rollback()
            if self.db.scalar(select(Incident.id).where(Incident.id == incident_id, Incident.is_deleted.is_(False))) is None:
                return None
            raise StaleDataError("Incident is being edited by another administrator.")
        self.db.commit()
        return self.get_by_id(incident_id)

    def set_verification(
        self,
        incident_id: UUID,
        status: str,
        reason: str | None,
        version: int,
        user_id: UUID,
    ) -> IncidentDetailDTO | None:
        incident = self.db.scalar(
            select(Incident).where(
                Incident.id == incident_id,
                Incident.is_deleted.is_(False),
                Incident.version == version,
            ).with_for_update()
        )
        if incident is None:
            self.db.rollback()
            if self.db.scalar(select(Incident.id).where(Incident.id == incident_id, Incident.is_deleted.is_(False))) is None:
                return None
            raise StaleDataError("Incident verification version is stale.")
        old_values = {
            "verification_status": incident.verification_status,
            "verification_reason": incident.verification_reason,
            "verified_by_user_id": str(incident.verified_by_user_id) if incident.verified_by_user_id else None,
        }
        incident.verification_status = status
        incident.verification_reason = reason
        incident.verified_by_user_id = user_id
        incident.verified_at = datetime.now(timezone.utc)
        self.db.add(IncidentUpdate(
            incident_id=incident.id,
            action=UpdateAction.status_change,
            old_values=old_values,
            new_values={"verification_status": status, "verification_reason": reason, "verified_by_user_id": str(user_id)},
            performed_by=user_id,
        ))
        self.db.commit()
        return self.get_by_id(incident_id)

    def get_pending_duplicate_candidate(
        self, incident_id: UUID
    ) -> IncidentDuplicateCandidateDTO | None:
        match = self.db.scalar(
            select(DuplicateMatch)
            .where(
                DuplicateMatch.incident_id == incident_id,
                DuplicateMatch.status == MatchStatus.pending,
                DuplicateMatch.matched_incident_id.is_not(None),
            )
            .order_by(DuplicateMatch.similarity_score.desc().nullslast())
        )
        if match is None or match.matched_incident_id is None:
            return None
        candidate = self.get_by_id(match.matched_incident_id)
        if candidate is None:
            return None
        return IncidentDuplicateCandidateDTO(
            match_id=match.id,
            similarity_score=float(match.similarity_score or 0.0),
            candidate=DuplicateCandidateIncidentDTO(
                id=candidate.id,
                village=candidate.village,
                condition=candidate.condition,
                event_date=candidate.event_date,
                event_time=candidate.event_time,
                khabar=candidate.khabar,
                source=candidate.source,
                source_reference=candidate.source_reference,
                total_deaths=candidate.total_deaths,
                total_injuries=candidate.total_injuries,
            ),
        )

    def resolve_duplicate(
        self,
        incident_id: UUID,
        match_id: int,
        decision: str,
        version: int,
        user_id: UUID,
    ) -> IncidentDuplicateResolutionResultDTO | None:
        incident = self.db.scalar(
            select(Incident).where(
                Incident.id == incident_id,
                Incident.is_deleted.is_(False),
                Incident.version == version,
                Incident.locked_by_user_id == user_id,
            ).with_for_update()
        )
        if incident is None:
            self.db.rollback()
            if self.db.scalar(select(Incident.id).where(Incident.id == incident_id, Incident.is_deleted.is_(False))) is None:
                return None
            raise StaleDataError("Incident version or edit lock is stale.")

        match = self.db.scalar(
            select(DuplicateMatch).where(
                DuplicateMatch.id == match_id,
                DuplicateMatch.incident_id == incident_id,
                DuplicateMatch.status == MatchStatus.pending,
                DuplicateMatch.matched_incident_id.is_not(None),
            ).with_for_update()
        )
        if match is None or match.matched_incident_id is None:
            self.db.rollback()
            raise StaleDataError("Duplicate match is missing or already resolved.")

        canonical_id = match.matched_incident_id
        if decision == MatchStatus.false_positive.value:
            incident.duplicate_flag = False
            match.status = MatchStatus.false_positive
        elif decision == MatchStatus.confirmed_duplicate.value:
            canonical = self.db.scalar(
                select(Incident).where(
                    Incident.id == canonical_id,
                    Incident.is_deleted.is_(False),
                ).with_for_update()
            )
            if canonical is None:
                self.db.rollback()
                raise StaleDataError("The suggested main incident is no longer available.")

            old_values = self._snapshot_merge_fields(canonical)
            for field in ("deaths", "injuries", "total_deaths", "total_injuries"):
                setattr(canonical, field, self._max_preserving_empty(getattr(canonical, field), getattr(incident, field)))
            if incident.khabar:
                addition = f"[Confirmed duplicate {incident.id}] {incident.khabar}"
                canonical.note = f"{canonical.note.rstrip()}\n\n{addition}" if canonical.note else addition
            if canonical.source_link is None:
                canonical.source_link = incident.source_link
            if canonical.source_link_2 is None:
                canonical.source_link_2 = incident.source_link_2 or incident.source_link

            duplicate_detail = self.db.scalar(select(IncidentDetail).where(IncidentDetail.incident_id == incident.id))
            if duplicate_detail is not None:
                canonical_detail = self.db.scalar(select(IncidentDetail).where(IncidentDetail.incident_id == canonical.id))
                if canonical_detail is None:
                    canonical_detail = IncidentDetail(incident_id=canonical.id)
                    self.db.add(canonical_detail)
                    self.db.flush()
                excluded = {"id", "incident_id", "created_at", "updated_at"}
                merge_incident_detail_fields(
                    canonical_detail,
                    {
                        column.name: getattr(duplicate_detail, column.name)
                        for column in IncidentDetail.__table__.columns
                        if column.name not in excluded
                    },
                )

            new_values = self._snapshot_merge_fields(canonical)
            self.db.add(IncidentUpdate(
                incident_id=canonical.id,
                action=UpdateAction.pipeline_merge,
                old_values=old_values,
                new_values=new_values,
                performed_by=user_id,
            ))
            incident.is_deleted = True
            incident.duplicate_flag = False
            match.status = MatchStatus.confirmed_duplicate
        else:
            self.db.rollback()
            raise ValueError("Unsupported duplicate resolution decision.")

        match.resolved_by = user_id
        incident.locked_by_user_id = None
        incident.edit_lock_expires_at = None
        self.db.add(IncidentUpdate(
            incident_id=incident.id,
            action=UpdateAction.status_change,
            old_values={"duplicate_flag": True, "duplicate_status": "pending"},
            new_values={"duplicate_flag": False, "duplicate_status": decision},
            performed_by=user_id,
        ))
        self.db.commit()
        return IncidentDuplicateResolutionResultDTO(
            decision=decision,
            incident_id=incident_id,
            canonical_incident_id=canonical_id if decision == MatchStatus.confirmed_duplicate.value else incident_id,
        )

    def release_edit_lock(self, incident_id: UUID, user_id: UUID) -> bool:
        result = self.db.execute(
            sa_update(Incident)
            .where(Incident.id == incident_id, Incident.locked_by_user_id == user_id)
            .values(locked_by_user_id=None, edit_lock_expires_at=None)
        )
        self.db.commit()
        return result.rowcount > 0

    def list_duplicate_candidates(
        self,
        village_id: int,
        event_date: date,
        khabar_embedding: list[float],
        window_days: int,
        exclude_raw_message_id: int | None = None,
    ) -> list[tuple[Incident, float]]:
        start_date = event_date - timedelta(days=window_days)
        end_date = event_date + timedelta(days=window_days)
        embedding_similarity = (
            1.0 - Incident.khabar_embedding.cosine_distance(khabar_embedding)
        ).label("embedding_similarity")
        filters = [
            Incident.village_id == village_id,
            Incident.is_deleted.is_(False),
            Incident.event_date >= start_date,
            Incident.event_date <= end_date,
            Incident.khabar_embedding.is_not(None),
        ]
        if exclude_raw_message_id is not None:
            filters.append(Incident.raw_message_id != exclude_raw_message_id)

        rows = self.db.execute(
            select(Incident, embedding_similarity)
            .where(and_(*filters))
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

    def create_fast_path_duplicate_match(
        self,
        *,
        canonical_incident: Incident,
        raw_message_id: int,
        status: MatchStatus = MatchStatus.pending,
        similarity_score: float | None = None,
    ) -> None:
        """Record a fast-path duplicate evaluation against an existing incident."""
        self.db.add(
            DuplicateMatch(
                incident_id=canonical_incident.id,
                matched_incident_id=None,
                raw_message_id=raw_message_id,
                match_type=MatchType.exact,
                similarity_score=similarity_score,
                status=status,
            )
        )
        self.db.flush()

    def redirect_pending_duplicate_matches(
        self,
        *,
        retired_incident: Incident,
        canonical_incident: Incident | None,
    ) -> int:
        """Keep pending review links pointed at an active canonical incident."""
        if canonical_incident is None or canonical_incident.id == retired_incident.id:
            return 0
        result = self.db.execute(
            sa_update(DuplicateMatch)
            .where(
                DuplicateMatch.matched_incident_id == retired_incident.id,
                DuplicateMatch.status == MatchStatus.pending,
            )
            .values(matched_incident_id=canonical_incident.id)
        )
        return int(result.rowcount or 0)

    def merge_existing(
        self,
        existing: Incident,
        new_candidate_data: dict[str, Any],
        raw_message_id: int,
    ) -> None:
        raw_message = self.db.get(RawMessage, raw_message_id)
        source_label = self._merge_source_label(raw_message)
        detail = self.db.scalar(
            select(IncidentDetail).where(IncidentDetail.incident_id == existing.id)
        )
        old_values = self._snapshot_merge_audit(existing, detail)
        parsed_transitions = parse_casualty_transitions(
            new_candidate_data.get("casualty_transitions")
        )
        backstop = detect_casualty_transition_backstop(
            raw_message.raw_text if raw_message is not None else new_candidate_data.get("khabar")
        )

        transition_fields, transition_provenance, needs_review = (
            apply_casualty_transitions(
                existing,
                parsed_transitions,
            )
        )
        if backstop.plausible and not parsed_transitions:
            needs_review = True
            transition_provenance["possible_missed_casualty_transition"] = {
                "matched_keywords": list(backstop.matched_keywords),
                "note": (
                    "possible casualty transition detected in text but not "
                    "extracted - needs verification"
                ),
            }
        if transition_provenance:
            for key in list(transition_provenance.keys()):
                transition_provenance[key] = {
                    **transition_provenance[key],
                    "raw_message_id": raw_message_id,
                    "channel": source_label,
                }
        if needs_review:
            existing.duplicate_flag = True
        else:
            # A successful automatic merge resolves its duplicate decision.
            # Keep the flag only for an explicit casualty-transition conflict.
            existing.duplicate_flag = False
        sync_transition_totals(existing, transition_fields)

        suppressed: dict[str, Any] = {}
        for field, incoming_key in (
            ("deaths", "deaths"),
            ("injuries", "injuries"),
            ("total_deaths", "total_deaths"),
            ("total_injuries", "total_injuries"),
        ):
            if field in transition_fields:
                continue
            incoming_value = new_candidate_data.get(incoming_key)
            if field.startswith("total_") and incoming_value is None:
                fallback_key = "deaths" if field == "total_deaths" else "injuries"
                incoming_value = new_candidate_data.get(fallback_key)
            current_value = getattr(existing, field)
            merged_value = self._max_preserving_empty(current_value, incoming_value)
            if (
                isinstance(incoming_value, int)
                and merged_value != incoming_value
            ):
                suppressed[f"{field}_suppressed"] = {
                    "value": incoming_value,
                    "raw_message_id": raw_message_id,
                    "channel": source_label,
                }
            setattr(existing, field, merged_value)

        mapped_fields = new_candidate_data.get("mapped_fields") or {}
        if mapped_fields:
            if detail is None:
                detail = IncidentDetail(incident_id=existing.id)
                self.db.add(detail)
                self.db.flush()
            if self._merge_introduces_new_presence_categories(detail, mapped_fields):
                existing.details_pending = True
            merge_incident_detail_fields(detail, mapped_fields)
            self.db.add(detail)

        khabar = new_candidate_data.get("khabar")
        if khabar:
            existing.note = self._append_note(existing.note, khabar, raw_message_id)

        new_values = self._snapshot_merge_audit(existing, detail)
        if transition_provenance:
            new_values = {**new_values, **transition_provenance}
        if suppressed:
            new_values = {**new_values, **suppressed}
        if old_values != new_values:
            self.db.add(
                IncidentUpdate(
                    incident_id=existing.id,
                    action=UpdateAction.pipeline_merge,
                    old_values=old_values,
                    new_values=new_values,
                    performed_by=None,
                )
            )
        self.db.add(existing)

    def find_active_incident_for_raw_message_village(
        self,
        raw_message_id: int,
        village_id: int,
    ) -> Incident | None:
        return self.db.scalar(
            select(Incident).where(
                Incident.raw_message_id == raw_message_id,
                Incident.village_id == village_id,
                Incident.is_deleted.is_(False),
            )
        )

    def has_active_incidents_for_raw_message(self, raw_message_id: int) -> bool:
        count = self.db.scalar(
            select(func.count(Incident.id)).where(
                Incident.raw_message_id == raw_message_id,
                Incident.is_deleted.is_(False),
            )
        )
        return int(count or 0) > 0

    def find_active_incident_in_fast_dedup_window(
        self,
        *,
        village_id: int,
        condition_id: int,
        message_datetime: datetime,
        window_days: int,
        exclude_raw_message_id: int | None = None,
    ) -> Incident | None:
        event_date = message_datetime.date()
        start_date = event_date - timedelta(days=window_days)
        end_date = event_date + timedelta(days=window_days)

        filters = [
            Incident.village_id == village_id,
            Incident.condition_id == condition_id,
            Incident.is_deleted.is_(False),
            Incident.event_date >= start_date,
            Incident.event_date <= end_date,
        ]
        if exclude_raw_message_id is not None:
            filters.append(Incident.raw_message_id != exclude_raw_message_id)

        return self.db.scalar(
            select(Incident)
            .where(*filters)
            .order_by(Incident.created_at.asc())
            .limit(1)
        )

    def soft_delete_for_raw_message_id(
        self,
        raw_message_id: int,
        *,
        representative_raw_message_id: int | None = None,
        similarity_score: float | None = None,
    ) -> list[UUID]:
        incidents = list(
            self.db.scalars(
                select(Incident).where(
                    Incident.raw_message_id == raw_message_id,
                    Incident.is_deleted.is_(False),
                )
            ).all()
        )
        for incident in incidents:
            representative_incident: Incident | None = None
            if representative_raw_message_id is not None:
                representative_incident = self.find_active_incident_for_raw_message_village(
                    representative_raw_message_id,
                    incident.village_id,
                )
            # Duplicate incident records are preserved (not soft-deleted) per
            # "Show imported incidents and preserve duplicate records"; still
            # repoint any pending review link onto the active canonical.
            self.redirect_pending_duplicate_matches(
                retired_incident=incident,
                canonical_incident=representative_incident,
            )
            self.db.add(incident)
            if representative_incident is not None:
                self.create_duplicate_match(
                    incident=incident,
                    matched_incident=representative_incident,
                    similarity_score=similarity_score or 0.0,
                )
        self.db.flush()
        return [incident.id for incident in incidents]

    def soft_delete_for_village_incident(
        self,
        raw_message_id: int,
        village_id: int,
        *,
        matched_incident_id: UUID | None = None,
        similarity_score: float | None = None,
    ) -> list[UUID]:
        """Soft-delete only the incident(s) for a specific (raw_message_id, village_id) pair."""
        incidents = list(
            self.db.scalars(
                select(Incident).where(
                    Incident.raw_message_id == raw_message_id,
                    Incident.village_id == village_id,
                    Incident.is_deleted.is_(False),
                )
            ).all()
        )
        matched_incident: Incident | None = None
        if matched_incident_id is not None:
            matched_incident = self.db.get(Incident, matched_incident_id)

        for incident in incidents:
            self.redirect_pending_duplicate_matches(
                retired_incident=incident,
                canonical_incident=matched_incident,
            )
            self.db.add(incident)
            if matched_incident is not None:
                self.create_duplicate_match(
                    incident=incident,
                    matched_incident=matched_incident,
                    similarity_score=similarity_score or 0.0,
                )
        self.db.flush()
        return [incident.id for incident in incidents]

    def begin_nested(self) -> AbstractContextManager[object]:
        return self.db.begin_nested()

    def rollback(self) -> None:
        self.db.rollback()

    @staticmethod
    def _low_confidence_match() -> object:
        # New shape stores a pre-computed flag; old shape stores the status directly.
        return or_(
            RawMessage.match_result["any_village_low_confidence"].astext == "true",
            RawMessage.match_result["village_match_status"].astext
            == "matched_low_confidence",
            RawMessage.match_result["condition_match_status"].astext
            == "matched_low_confidence",
        )

    @classmethod
    def _list_filters(cls, params: IncidentListParams) -> list[object]:
        filters: list[object] = [
            Incident.is_deleted.is_(False),
            or_(
                RawMessage.id.is_(None),
                ~RawMessage.raw_payload.op("?")("ocr_text"),
            ),
        ]
        if params.village:
            village_pattern = f"%{params.village}%"
            filters.append(
                or_(
                    Village.ref_name_en.ilike(village_pattern),
                    Village.cad_name.ilike(village_pattern),
                    Village.ref_name_ar.ilike(village_pattern),
                )
            )
        if params.condition:
            filters.append(
                or_(
                    Condition.action_en.ilike(f"%{params.condition}%"),
                    Condition.action_ar.ilike(f"%{params.condition}%"),
                )
            )
        if params.source_type:
            filters.append(Source.type == params.source_type.lower())
        if params.event_date_from is not None:
            filters.append(Incident.event_date >= params.event_date_from)
        if params.event_date_to is not None:
            filters.append(Incident.event_date <= params.event_date_to)
        if params.flagged_only:
            filters.append(
                or_(
                    Incident.duplicate_flag.is_(True),
                    cls._low_confidence_match(),
                )
            )
        if params.verification_status == "needs_verification":
            filters.append(func.coalesce(cls._low_confidence_match(), False).is_(True))
        elif params.verification_status == "matched":
            filters.append(func.coalesce(cls._low_confidence_match(), False).is_(False))
        elif params.verification_status is not None:
            filters.append(Incident.verification_status == params.verification_status)
        if params.duplicate_only:
            filters.append(Incident.duplicate_flag.is_(True))
        return filters

    @staticmethod
    def _list_ordering(params: IncidentListParams) -> tuple[object, ...]:
        event_datetime = func.coalesce(
            RawMessage.message_datetime,
            RawMessage.received_at,
        )
        event_date = func.coalesce(
            Incident.event_date,
            func.date(event_datetime),
        )
        created_at = func.coalesce(Incident.created_at, RawMessage.received_at)
        raw_message_sort_id = func.coalesce(RawMessage.id, 0)
        if params.sort_order == "oldest":
            return (
                created_at.asc(),
                event_date.asc(),
                Incident.event_time.asc().nullslast(),
                raw_message_sort_id.asc(),
                Incident.id.asc().nullslast(),
            )
        return (
            created_at.desc(),
            event_date.desc(),
            Incident.event_time.desc().nullslast(),
            raw_message_sort_id.desc(),
            Incident.id.desc().nullslast(),
        )

    @staticmethod
    def _decode_list_cursor(cursor: str | None) -> dict[str, object] | None:
        if cursor is None:
            return None
        try:
            payload = json.loads(
                base64.urlsafe_b64decode(cursor.encode("ascii") + b"===")
            )
            created_at = datetime.fromisoformat(payload["sort_created_at"])
            event_date = date.fromisoformat(payload["sort_event_date"])
            event_time_is_null = payload["sort_event_time_is_null"]
            event_time = (
                None
                if event_time_is_null
                else time.fromisoformat(payload["sort_event_time"])
            )
            incident_id = payload["incident_id"]
            raw_message_id = payload["raw_message_id"]
            return {
                "sort_created_at": created_at,
                "sort_event_date": event_date,
                "sort_event_time_is_null": event_time_is_null,
                "sort_event_time": event_time,
                "raw_message_id": (
                    int(raw_message_id) if raw_message_id is not None else None
                ),
                "incident_id": UUID(incident_id) if incident_id is not None else None,
            }
        except (KeyError, TypeError, ValueError, UnicodeDecodeError) as exc:
            raise ValueError("Invalid incidents cursor.") from exc

    @staticmethod
    def _encode_list_cursor(row: Any) -> str:
        event_time = row["event_time"]
        payload = {
            "sort_created_at": row["created_at"].isoformat(),
            "sort_event_date": row["event_date"].isoformat(),
            "sort_event_time_is_null": event_time is None,
            "sort_event_time": event_time.isoformat() if event_time is not None else None,
            "raw_message_id": row["raw_message_id"],
            "incident_id": str(row["id"]) if row["id"] is not None else None,
        }
        return base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
        ).decode("ascii").rstrip("=")

    @staticmethod
    def _list_cursor_filter(
        params: IncidentListParams,
        cursor: dict[str, object],
        created_at: object,
        event_date: object,
    ) -> object:
        created_value = cursor["sort_created_at"]
        event_date_value = cursor["sort_event_date"]
        event_time_value = cursor["sort_event_time"]
        raw_message_id = cursor["raw_message_id"]
        raw_message_sort_id = func.coalesce(RawMessage.id, 0)
        raw_message_sort_value = raw_message_id if raw_message_id is not None else 0
        incident_id = cursor["incident_id"]
        before = params.sort_order == "newest"
        comparison = (lambda column, value: column < value) if before else (lambda column, value: column > value)
        created_equal = created_at == created_value
        event_date_equal = event_date == event_date_value
        event_time_after = (
            Incident.event_time.is_(None)
            if event_time_value is not None
            else false()
        )
        if event_time_value is not None:
            event_time_after = or_(
                comparison(Incident.event_time, event_time_value),
                Incident.event_time.is_(None),
            )
        incident_after = (
            or_(Incident.id.is_(None), comparison(Incident.id, incident_id))
            if incident_id is not None
            else false()
        )
        return or_(
            comparison(created_at, created_value),
            and_(created_equal, comparison(event_date, event_date_value)),
            and_(created_equal, event_date_equal, event_time_after),
            and_(
                created_equal,
                event_date_equal,
                (
                    Incident.event_time.is_(None)
                    if event_time_value is None
                    else Incident.event_time.is_not(None)
                ),
                comparison(raw_message_sort_id, raw_message_sort_value),
            ),
            and_(
                created_equal,
                event_date_equal,
                (
                    Incident.event_time.is_(None)
                    if event_time_value is None
                    else Incident.event_time.is_not(None)
                ),
                raw_message_sort_id == raw_message_sort_value,
                incident_after,
            ),
        )

    @staticmethod
    def _has_incident_scoped_filters(params: IncidentListParams) -> bool:
        return bool(
            params.village
            or params.condition
            or params.source_type
            or params.event_date_from is not None
            or params.event_date_to is not None
            or params.flagged_only
            or params.verification_status is not None
            or params.duplicate_only
        )

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
            "details_pending": incident.details_pending,
        }

    @classmethod
    def _snapshot_merge_audit(
        cls,
        incident: Incident,
        detail: IncidentDetail | None,
    ) -> dict[str, Any]:
        snapshot = cls._snapshot_merge_fields(incident)
        if detail is None:
            return snapshot
        for key in detail.__table__.columns.keys():
            if key == "incident_id":
                continue
            snapshot[f"detail.{key}"] = getattr(detail, key)
        return snapshot

    @staticmethod
    def _merge_introduces_new_presence_categories(
        detail: IncidentDetail,
        mapped_fields: dict[str, Any],
    ) -> bool:
        for key, value in mapped_fields.items():
            if value is not True:
                continue
            column = IncidentDetail.__table__.columns.get(key)
            if column is None or column.type.python_type is not bool:
                continue
            if getattr(detail, key) is not True:
                return True
        return False

    @staticmethod
    def _merge_source_label(raw_message: RawMessage | None) -> str | None:
        if raw_message is None:
            return None
        for candidate in (
            raw_message.source_name,
            raw_message.origin_account,
            raw_message.source_platform,
        ):
            if candidate:
                return str(candidate)
        return None

    @staticmethod
    def _source_reference_expression() -> object:
        return func.coalesce(
            func.nullif(RawMessage.origin_account, ""),
            func.nullif(RawMessage.source_name, ""),
            RawMessage.external_message_id,
        )

    @staticmethod
    def _sanitize_optional_text(value: str | None) -> str | None:
        if value is None:
            return None
        sanitized = strip_emoji_and_pictographs(value).strip()
        return sanitized or None

    def _ensure_manual_source(self) -> Source:
        source = self.db.scalar(
            select(Source).where(Source.type == SourceType.manual).limit(1)
        )
        if source is not None:
            return source

        source = Source(
            type=SourceType.manual,
            name="Manual Entry",
            external_id="manual_incidents",
            config={},
            is_active=True,
        )
        self.db.add(source)
        self.db.flush()
        return source
