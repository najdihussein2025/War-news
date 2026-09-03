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
    IncidentDetailDTO,
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
    MessageStatus,
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
                case(
                    (Incident.duplicate_flag.is_(True), "possible"),
                    else_="none",
                ).label("duplicate_flag"),
                func.coalesce(Incident.details_pending, true()).label(
                    "details_pending"
                ),
                created_at.label("created_at"),
                func.coalesce(Incident.version, 1).label("version"),
                Incident.locked_by_user_id,
                Incident.edit_lock_expires_at,
            )
            .select_from(RawMessage)
            .outerjoin(
                Incident,
                and_(
                    Incident.raw_message_id == RawMessage.id,
                    Incident.is_deleted.is_(False),
                ),
            )
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
            select(func.count(RawMessage.id))
            .select_from(RawMessage)
            .outerjoin(
                Incident,
                and_(
                    Incident.raw_message_id == RawMessage.id,
                    Incident.is_deleted.is_(False),
                ),
            )
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
            .select_from(RawMessage)
            .outerjoin(
                Incident,
                and_(
                    Incident.raw_message_id == RawMessage.id,
                    Incident.is_deleted.is_(False),
                ),
            )
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
            .select_from(RawMessage)
            .outerjoin(
                Incident,
                and_(
                    Incident.raw_message_id == RawMessage.id,
                    Incident.is_deleted.is_(False),
                ),
            )
            .where(
                RawMessage.status.in_(
                    [MessageStatus.parsed, MessageStatus.materialized]
                ),
                ~RawMessage.raw_payload.op("?")("ocr_text"),
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
            "duplicate_flag": row.duplicate_flag,
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
        existing.injuries = self._max_preserving_empty(
            existing.injuries,
            new_candidate_data.get("injuries"),
        )
        existing.total_deaths = self._max_preserving_empty(
            existing.total_deaths,
            new_candidate_data.get("total_deaths", new_candidate_data.get("deaths")),
        )
        existing.total_injuries = self._max_preserving_empty(
            existing.total_injuries,
            new_candidate_data.get(
                "total_injuries",
                new_candidate_data.get("injuries"),
            ),
        )

        mapped_fields = new_candidate_data.get("mapped_fields") or {}
        if mapped_fields:
            detail = self.db.scalar(
                select(IncidentDetail).where(IncidentDetail.incident_id == existing.id)
            )
            if detail is None:
                detail = IncidentDetail(incident_id=existing.id)
                self.db.add(detail)
                self.db.flush()
            merge_incident_detail_fields(detail, mapped_fields)
            self.db.add(detail)

        khabar = new_candidate_data.get("khabar")
        if khabar:
            existing.note = self._append_note(existing.note, khabar, raw_message_id)

        new_values = self._snapshot_merge_fields(existing)
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
            incident.is_deleted = True
            self.db.add(incident)
            if representative_raw_message_id is not None:
                representative_incident = self.find_active_incident_for_raw_message_village(
                    representative_raw_message_id,
                    incident.village_id,
                )
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
            incident.is_deleted = True
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
            RawMessage.status.in_(
                [
                    MessageStatus.parsed,
                    MessageStatus.materialized,
                ]
            ),
            ~RawMessage.raw_payload.op("?")("ocr_text"),
        ]
        if cls._has_incident_scoped_filters(params):
            filters.append(Incident.id.is_not(None))
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
        if params.sort_order == "oldest":
            return (
                created_at.asc(),
                event_date.asc(),
                Incident.event_time.asc().nullslast(),
                RawMessage.id.asc(),
                Incident.id.asc().nullslast(),
            )
        return (
            created_at.desc(),
            event_date.desc(),
            Incident.event_time.desc().nullslast(),
            RawMessage.id.desc(),
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
            return {
                "sort_created_at": created_at,
                "sort_event_date": event_date,
                "sort_event_time_is_null": event_time_is_null,
                "sort_event_time": event_time,
                "raw_message_id": int(payload["raw_message_id"]),
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
                comparison(RawMessage.id, raw_message_id),
            ),
            and_(
                created_equal,
                event_date_equal,
                (
                    Incident.event_time.is_(None)
                    if event_time_value is None
                    else Incident.event_time.is_not(None)
                ),
                RawMessage.id == raw_message_id,
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
        }

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
