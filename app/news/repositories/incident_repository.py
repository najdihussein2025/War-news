import hashlib
from contextlib import AbstractContextManager
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, case, desc, func, or_, select
from sqlalchemy.orm import Session

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

        base_query = (
            select(
                Incident.id,
                Incident.raw_message_id,
                func.coalesce(Village.ref_name_en, Village.cad_name).label("village"),
                Condition.action_en.label("condition"),
                Incident.event_date,
                Incident.event_time,
                Incident.khabar,
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
                case((low_confidence, False), else_=True).label("matched"),
                case(
                    (Incident.duplicate_flag.is_(True), "possible"),
                    else_="none",
                ).label("duplicate_flag"),
                Incident.details_pending,
                Incident.created_at,
            )
            .outerjoin(Village, Village.id == Incident.village_id)
            .outerjoin(Condition, Condition.id == Incident.condition_id)
            .outerjoin(Source, Source.id == Incident.source_id)
            .outerjoin(RawMessage, RawMessage.id == Incident.raw_message_id)
            .where(*filters)
        )

        rows = self.db.execute(
            base_query.order_by(
                Incident.created_at.desc(),
                Incident.event_date.desc(),
                Incident.event_time.desc().nullslast(),
            )
            .limit(params.limit)
            .offset(params.offset)
        ).all()
        total = self.db.scalar(
            select(func.count(Incident.id))
            .outerjoin(Village, Village.id == Incident.village_id)
            .outerjoin(Condition, Condition.id == Incident.condition_id)
            .outerjoin(Source, Source.id == Incident.source_id)
            .outerjoin(RawMessage, RawMessage.id == Incident.raw_message_id)
            .where(*filters)
        )
        latest_incident_at = self.db.scalar(
            select(
                func.max(
                    func.greatest(Incident.created_at, Incident.updated_at)
                )
            )
            .outerjoin(Village, Village.id == Incident.village_id)
            .outerjoin(Condition, Condition.id == Incident.condition_id)
            .outerjoin(Source, Source.id == Incident.source_id)
            .outerjoin(RawMessage, RawMessage.id == Incident.raw_message_id)
            .where(*filters)
        )

        return IncidentListResponse(
            items=[
                IncidentListItemDTO.model_validate(row._mapping)
                for row in rows
            ],
            total=int(total or 0),
            limit=params.limit,
            offset=params.offset,
            latest_incident_at=latest_incident_at,
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
            "khabar": incident.khabar,
            "note": incident.note,
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

    def update(self, incident_id: UUID, payload: IncidentUpdateDTO) -> IncidentDetailDTO | None:
        incident = self.db.scalar(
            select(Incident).where(Incident.id == incident_id, Incident.is_deleted.is_(False))
        )
        if incident is None:
            return None
        text_fields = {
            "khabar",
            "note",
            "worker_name",
            "source_link",
            "source_link_2",
        }
        for field, value in payload.model_dump().items():
            if field in text_fields:
                value = self._sanitize_optional_text(value)
                if field == "khabar" and value is None:
                    value = ""
            setattr(incident, field, value)
        incident.event_month = payload.event_date.strftime("%B")
        self.db.commit()
        return self.get_by_id(incident_id)

    def update_details(
        self,
        incident_id: UUID,
        fields: dict[str, Any],
        performed_by: UUID,
    ) -> IncidentDetailDTO | None:
        incident = self.db.scalar(
            select(Incident).where(
                Incident.id == incident_id,
                Incident.is_deleted.is_(False),
            )
        )
        if incident is None:
            return None

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
        self.db.commit()
        return self.get_by_id(incident_id)

    def delete(self, incident_id: UUID) -> bool:
        incident = self.db.scalar(
            select(Incident).where(Incident.id == incident_id, Incident.is_deleted.is_(False))
        )
        if incident is None:
            return False
        incident.is_deleted = True
        self.db.commit()
        return True

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
        window_minutes: int,
        exclude_raw_message_id: int | None = None,
    ) -> Incident | None:
        window = timedelta(minutes=window_minutes)
        start = message_datetime - window
        end = message_datetime + window

        filters = [
            Incident.village_id == village_id,
            Incident.condition_id == condition_id,
            Incident.is_deleted.is_(False),
            RawMessage.message_datetime.is_not(None),
            RawMessage.message_datetime >= start,
            RawMessage.message_datetime <= end,
        ]
        if exclude_raw_message_id is not None:
            filters.append(Incident.raw_message_id != exclude_raw_message_id)

        return self.db.scalar(
            select(Incident)
            .join(RawMessage, RawMessage.id == Incident.raw_message_id)
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
        filters: list[object] = [Incident.is_deleted.is_(False)]
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
