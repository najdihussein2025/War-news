from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.news.dtos import (
    AirViolationDTO,
    AirViolationListParams,
    AirViolationListResponse,
    MatchResultDTO,
)
from app.news.interfaces import AirViolationRepositoryInterface
from app.news.models import (
    AirViolation,
    Condition,
    RawMessage,
    Village,
)
from app.sources.models import Source


class AirViolationRepository(AirViolationRepositoryInterface):
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_all(self, params: AirViolationListParams) -> AirViolationListResponse:
        filters = self._filters(params)

        base_query = (
            select(
                AirViolation.id,
                AirViolation.raw_message_id,
                AirViolation.condition_id,
                AirViolation.source_id,
                AirViolation.caza_en,
                AirViolation.caza_ar,
                AirViolation.event_month,
                AirViolation.event_date,
                AirViolation.event_time,
                AirViolation.khabar,
                AirViolation.note_1,
                AirViolation.note_2,
                AirViolation.source_link,
                AirViolation.created_at,
                Condition.action_en,
                Condition.action_ar,
                Source.name.label("source_name"),
            )
            .join(Condition, Condition.id == AirViolation.condition_id)
            .join(Source, Source.id == AirViolation.source_id)
            .where(*filters)
        )

        rows = self.db.execute(
            base_query.order_by(
                AirViolation.event_date.desc(),
                AirViolation.event_time.desc().nullslast(),
                AirViolation.id.desc(),
            )
            .limit(params.limit)
            .offset(params.offset)
        ).all()
        total = self.db.scalar(
            select(func.count(AirViolation.id))
            .join(Condition, Condition.id == AirViolation.condition_id)
            .join(Source, Source.id == AirViolation.source_id)
            .where(*filters)
        )

        return AirViolationListResponse(
            items=[AirViolationDTO.model_validate(row._mapping) for row in rows],
            total=int(total or 0),
            limit=params.limit,
            offset=params.offset,
        )

    def get_detail(self, air_violation_id: int) -> AirViolationDTO | None:
        row = self.db.execute(
            select(
                AirViolation.id,
                AirViolation.raw_message_id,
                AirViolation.condition_id,
                AirViolation.source_id,
                AirViolation.caza_en,
                AirViolation.caza_ar,
                AirViolation.event_month,
                AirViolation.event_date,
                AirViolation.event_time,
                AirViolation.khabar,
                AirViolation.note_1,
                AirViolation.note_2,
                AirViolation.source_link,
                AirViolation.created_at,
                Condition.action_en,
                Condition.action_ar,
                Source.name.label("source_name"),
            )
            .join(Condition, Condition.id == AirViolation.condition_id)
            .join(Source, Source.id == AirViolation.source_id)
            .where(AirViolation.id == air_violation_id)
        ).one_or_none()
        if row is None:
            return None
        return AirViolationDTO.model_validate(row._mapping)

    def route_from_match(self, message: RawMessage, result: MatchResultDTO) -> None:
        if result.matched_condition_id not in {35, 36, 38} or result.matched_village_id is None:
            return
        if self.db.scalar(select(AirViolation.id).where(AirViolation.raw_message_id == message.id)) is not None:
            return
        village = self.db.get(Village, result.matched_village_id)
        if village is None:
            return
        occurred_at = message.message_datetime or message.received_at
        payload = message.raw_payload or {}
        link = next((payload.get(key) for key in ("source_link", "link", "url", "post_url") if payload.get(key)), None)
        self.db.add(AirViolation(
            raw_message_id=message.id,
            condition_id=result.matched_condition_id,
            source_id=message.source_id,
            caza_en=village.caza_en,
            caza_ar=village.caza_ar,
            event_month=occurred_at.strftime("%B"),
            event_date=occurred_at.date(),
            event_time=occurred_at.time().replace(tzinfo=None),
            khabar=message.raw_text or "",
            note_1=payload.get("note_1") or payload.get("note"),
            note_2=payload.get("note_2"),
            source_link=str(link) if link else None,
        ))
        self.db.commit()

    @staticmethod
    def _filters(params: AirViolationListParams) -> list[object]:
        filters: list[object] = []
        if params.condition_id is not None:
            filters.append(AirViolation.condition_id == params.condition_id)
        if params.event_date_from is not None:
            filters.append(AirViolation.event_date >= params.event_date_from)
        if params.event_date_to is not None:
            filters.append(AirViolation.event_date <= params.event_date_to)
        if params.caza_en:
            filters.append(AirViolation.caza_en.ilike(f"%{params.caza_en}%"))
        return filters
