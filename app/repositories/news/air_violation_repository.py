from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.dtos.news import (
    AirViolationDTO,
    AirViolationListParams,
    AirViolationListResponse,
)
from app.interfaces.repositories import AirViolationRepositoryInterface
from app.models.news import AirViolation, Condition, Source


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
