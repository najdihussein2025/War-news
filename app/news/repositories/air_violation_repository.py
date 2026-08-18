from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.news.dtos import (
    AirViolationCreateDTO,
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
from app.sources.models import Source, SourceType


class AirViolationRepository(AirViolationRepositoryInterface):
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, payload: AirViolationCreateDTO) -> AirViolationDTO:
        source = self.db.scalar(
            select(Source).where(Source.external_id == "manual_air_violations")
        )
        if source is None:
            source = Source(
                type=SourceType.manual,
                name="Manual Entry",
                external_id="manual_air_violations",
                config={},
            )
            self.db.add(source)
            self.db.flush()

        record = AirViolation(
            condition_id=payload.condition_id,
            source_id=source.id,
            caza_en=payload.caza_en,
            caza_ar=payload.caza_ar,
            event_month=payload.event_date.strftime("%B"),
            event_date=payload.event_date,
            event_time=payload.event_time,
            khabar=payload.khabar,
            note_1=payload.note_1,
            note_2=payload.note_2,
            source_link=payload.source_link,
        )
        self.db.add(record)
        self.db.commit()
        detail = self.get_detail(record.id)
        if detail is None:
            raise RuntimeError("Created air violation could not be loaded.")
        return detail

    def update(
        self,
        air_violation_id: int,
        payload: AirViolationCreateDTO,
    ) -> AirViolationDTO | None:
        record = self.db.get(AirViolation, air_violation_id)
        if record is None:
            return None
        record.condition_id = payload.condition_id
        record.caza_en = payload.caza_en
        record.caza_ar = payload.caza_ar
        record.event_month = payload.event_date.strftime("%B")
        record.event_date = payload.event_date
        record.event_time = payload.event_time
        record.khabar = payload.khabar
        record.note_1 = payload.note_1
        record.note_2 = payload.note_2
        record.source_link = payload.source_link
        self.db.commit()
        return self.get_detail(record.id)

    def delete(self, air_violation_id: int) -> bool:
        record = self.db.get(AirViolation, air_violation_id)
        if record is None:
            return False
        self.db.delete(record)
        self.db.commit()
        return True

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
                case(
                    (
                        RawMessage.id.is_not(None),
                        func.coalesce(
                            func.nullif(RawMessage.origin_account, "CNRS Webhook"),
                            func.nullif(RawMessage.source_name, "CNRS Webhook"),
                            "Unknown source",
                        ),
                    ),
                    else_=Source.name,
                ).label("source_name"),
            )
            .join(Condition, Condition.id == AirViolation.condition_id)
            .join(Source, Source.id == AirViolation.source_id)
            .outerjoin(RawMessage, RawMessage.id == AirViolation.raw_message_id)
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
                case(
                    (
                        RawMessage.id.is_not(None),
                        func.coalesce(
                            func.nullif(RawMessage.origin_account, "CNRS Webhook"),
                            func.nullif(RawMessage.source_name, "CNRS Webhook"),
                            "Unknown source",
                        ),
                    ),
                    else_=Source.name,
                ).label("source_name"),
            )
            .join(Condition, Condition.id == AirViolation.condition_id)
            .join(Source, Source.id == AirViolation.source_id)
            .outerjoin(RawMessage, RawMessage.id == AirViolation.raw_message_id)
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
