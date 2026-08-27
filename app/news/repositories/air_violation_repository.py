import re
from datetime import datetime, time, timedelta
from uuid import UUID

from sqlalchemy import case, delete as sa_delete, func, select, update as sa_update
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError
from zoneinfo import ZoneInfo

from app.core.text_sanitizer import strip_emoji_and_pictographs
from app.core.cache import increment
from app.news.dtos import (
    AirViolationCreateDTO,
    AirViolationDTO,
    AirViolationListParams,
    AirViolationListResponse,
    AirViolationSummaryDTO,
    AirViolationUpdateDTO,
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


BEIRUT_TIMEZONE = ZoneInfo("Asia/Beirut")
AIR_VIOLATION_CACHE_VERSION_KEY = "air-violations:cache-version"


def as_beirut_datetime(value):
    """Convert aware upstream timestamps to local Beirut time for display/storage."""
    if value.tzinfo is None:
        return value
    return value.astimezone(BEIRUT_TIMEZONE)


def air_violation_news_text(
    message: RawMessage,
    village: Village | None,
    condition: Condition | None,
) -> str:
    """Return readable news text while keeping raw OCR in the source record."""
    payload = message.raw_payload or {}
    if not payload.get("ocr_text") or condition is None:
        return clean_air_violation_news(message.raw_text or "")

    if village is None:
        return f"{condition.action_ar} - الموقع بحاجة إلى التحقق"
    village_name = (
        getattr(village, "ref_name_ar", None)
        or getattr(village, "ref_name_en", None)
        or getattr(village, "acs_name", None)
        or getattr(village, "cad_name", None)
    )
    caza_name = village.caza_ar or village.caza_en
    summary = (
        f"{condition.action_ar} فوق {village_name} في قضاء {caza_name}"
        if village_name
        else f"{condition.action_ar} في قضاء {caza_name}"
    )
    raw_text = message.raw_text or ""
    if "حيطة" in raw_text and "حذر" in raw_text:
        summary += " - حيطة وحذر"
    return clean_air_violation_news(summary)


def clean_air_violation_news(value: str) -> str:
    """Remove decorative symbols while preserving meaningful multilingual text."""
    cleaned_lines: list[str] = []
    for raw_line in strip_emoji_and_pictographs(value).splitlines():
        line = raw_line
        line = re.sub(r"[ \t]+", " ", line).strip()
        if line:
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def air_violation_caza_labels(
    text: str,
    default_caza_en: str | None,
    default_caza_ar: str | None,
    known_cazas: list[tuple[str | None, str | None]],
) -> tuple[str | None, str | None]:
    """Label bulletins naming several cazas without choosing a false locality."""
    normalized_text = text.casefold()
    mentioned: set[tuple[str | None, str | None]] = set()
    for caza_en, caza_ar in known_cazas:
        names = [name.casefold() for name in (caza_en, caza_ar) if name and len(name) >= 4]
        if any(re.search(rf"(?<!\w){re.escape(name)}(?!\w)", normalized_text) for name in names):
            mentioned.add((caza_en, caza_ar))
    if len(mentioned) > 1:
        return "Multiple regions", "مناطق متعددة"
    if len(mentioned) == 1:
        return next(iter(mentioned))
    return default_caza_en, default_caza_ar


class AirViolationRepository(AirViolationRepositoryInterface):
    def __init__(self, db: Session) -> None:
        self.db = db

    def _with_village_labels(self, rows: list[object]) -> list[dict[str, object]]:
        data = [dict(row._mapping) for row in rows]
        village_ids: set[int] = set()
        for item in data:
            result = item.pop("raw_match_result", None) or {}
            matches = result.get("village_matches") or []
            matched_village_id = (
                matches[0].get("matched_village_id")
                if matches
                else result.get("matched_village_id")
            )
            if matched_village_id is not None:
                village_id = int(matched_village_id)
                item["matched_village_id"] = village_id
                village_ids.add(village_id)

        villages = {
            village.id: village
            for village in self.db.scalars(
                select(Village).where(Village.id.in_(village_ids))
            )
        } if village_ids else {}
        for item in data:
            village = villages.get(item.pop("matched_village_id", None))
            item["village_en"] = (
                village.ref_name_en or village.acs_name or village.cad_name
                if village
                else item.get("caza_en")
            )
            item["village_ar"] = village.ref_name_ar if village else item.get("caza_ar")
        return data

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
        increment(AIR_VIOLATION_CACHE_VERSION_KEY)
        detail = self.get_detail(record.id)
        if detail is None:
            raise RuntimeError("Created air violation could not be loaded.")
        return detail

    def update(
        self,
        air_violation_id: int,
        payload: AirViolationUpdateDTO,
        user_id: UUID,
    ) -> AirViolationDTO | None:
        result = self.db.execute(
            sa_update(AirViolation)
            .where(
                AirViolation.id == air_violation_id,
                AirViolation.version == payload.version,
                AirViolation.locked_by_user_id == user_id,
            )
            .values(
                condition_id=payload.condition_id,
                caza_en=payload.caza_en,
                caza_ar=payload.caza_ar,
                event_month=payload.event_date.strftime("%B"),
                event_date=payload.event_date,
                event_time=payload.event_time,
                khabar=payload.khabar,
                note_1=payload.note_1,
                note_2=payload.note_2,
                source_link=payload.source_link,
                version=AirViolation.version + 1,
                locked_by_user_id=None,
                edit_lock_expires_at=None,
            )
        )
        if result.rowcount == 0:
            self.db.rollback()
            if self.db.get(AirViolation, air_violation_id) is None:
                return None
            raise StaleDataError("Air violation version is stale.")
        self.db.commit()
        increment(AIR_VIOLATION_CACHE_VERSION_KEY)
        return self.get_detail(air_violation_id)

    def delete(self, air_violation_id: int, version: int, user_id: UUID) -> bool:
        result = self.db.execute(
            sa_delete(AirViolation).where(
                AirViolation.id == air_violation_id,
                AirViolation.version == version,
                AirViolation.locked_by_user_id == user_id,
            )
        )
        if result.rowcount == 0:
            self.db.rollback()
            if self.db.get(AirViolation, air_violation_id) is None:
                return False
            raise StaleDataError("Air violation version is stale.")
        self.db.commit()
        increment(AIR_VIOLATION_CACHE_VERSION_KEY)
        return True

    def acquire_edit_lock(self, air_violation_id: int, user_id: UUID) -> AirViolationDTO | None:
        now = datetime.now(BEIRUT_TIMEZONE)
        result = self.db.execute(
            sa_update(AirViolation)
            .where(
                AirViolation.id == air_violation_id,
                (
                    AirViolation.locked_by_user_id.is_(None)
                    | (AirViolation.edit_lock_expires_at <= now)
                    | (AirViolation.locked_by_user_id == user_id)
                ),
            )
            .values(
                locked_by_user_id=user_id,
                edit_lock_expires_at=now + timedelta(minutes=5),
            )
        )
        if result.rowcount == 0:
            self.db.rollback()
            if self.db.get(AirViolation, air_violation_id) is None:
                return None
            raise StaleDataError("Air violation is being edited by another administrator.")
        self.db.commit()
        return self.get_detail(air_violation_id)

    def release_edit_lock(self, air_violation_id: int, user_id: UUID) -> bool:
        result = self.db.execute(
            sa_update(AirViolation)
            .where(
                AirViolation.id == air_violation_id,
                AirViolation.locked_by_user_id == user_id,
            )
            .values(locked_by_user_id=None, edit_lock_expires_at=None)
        )
        self.db.commit()
        return result.rowcount > 0

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
                AirViolation.version,
                AirViolation.locked_by_user_id,
                AirViolation.edit_lock_expires_at,
                AirViolation.created_at,
                RawMessage.match_result.label("raw_match_result"),
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
            items=[
                AirViolationDTO.model_validate(item)
                for item in self._with_village_labels(rows)
            ],
            total=int(total or 0),
            limit=params.limit,
            offset=params.offset,
        )

    def get_summary(self, params: AirViolationListParams) -> AirViolationSummaryDTO:
        rows = self.db.execute(
            select(AirViolation.condition_id, func.count(AirViolation.id))
            .where(*self._filters(params))
            .group_by(AirViolation.condition_id)
        ).all()
        counts = {condition_id: int(count) for condition_id, count in rows}
        return AirViolationSummaryDTO(
            warplanes=counts.get(35, 0),
            surveillance_aircraft=counts.get(36, 0),
            helicopters=counts.get(38, 0),
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
                AirViolation.version,
                AirViolation.locked_by_user_id,
                AirViolation.edit_lock_expires_at,
                AirViolation.created_at,
                RawMessage.match_result.label("raw_match_result"),
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
        return AirViolationDTO.model_validate(self._with_village_labels([row])[0])

    def route_from_match(self, message: RawMessage, result: MatchResultDTO) -> bool:
        if result.matched_condition_id not in {35, 36, 38, 45}:
            return False
        matched_village_id: int | None = next(
            (
                vm.matched_village_id
                for vm in result.village_matches
                if vm.matched_village_id is not None
            ),
            None,
        )
        existing = self.db.scalar(
            select(AirViolation).where(AirViolation.raw_message_id == message.id)
        )
        village = self.db.get(Village, matched_village_id) if matched_village_id is not None else None
        if matched_village_id is not None and village is None:
            return False
        condition = self.db.get(Condition, result.matched_condition_id)
        occurred_at = as_beirut_datetime(message.message_datetime or message.received_at)
        payload = message.raw_payload or {}
        link = next((payload.get(key) for key in ("source_link", "link", "url", "post_url") if payload.get(key)), None)
        known_cazas = list(
            self.db.execute(select(Village.caza_en, Village.caza_ar).distinct()).all()
        )
        caza_en, caza_ar = air_violation_caza_labels(
            message.raw_text or "",
            village.caza_en if village else None,
            village.caza_ar if village else None,
            known_cazas,
        )
        values = {
            "condition_id": result.matched_condition_id,
            "source_id": message.source_id,
            "caza_en": caza_en,
            "caza_ar": caza_ar,
            "event_month": occurred_at.strftime("%B"),
            "event_date": occurred_at.date(),
            "event_time": occurred_at.time().replace(tzinfo=None),
            "khabar": air_violation_news_text(message, village, condition),
            "note_1": payload.get("note_1") or payload.get("note"),
            "note_2": payload.get("note_2"),
            "source_link": str(link) if link else None,
        }
        if existing is None:
            self.db.add(AirViolation(raw_message_id=message.id, **values))
        else:
            for field, value in values.items():
                setattr(existing, field, value)
        self.db.commit()
        increment(AIR_VIOLATION_CACHE_VERSION_KEY)
        return True

    @staticmethod
    def _filters(params: AirViolationListParams) -> list[object]:
        filters: list[object] = []
        if params.condition_id is not None:
            filters.append(AirViolation.condition_id == params.condition_id)
        if params.event_date_from is not None:
            filters.append(AirViolation.event_date >= params.event_date_from)
        if params.event_date_to is not None:
            filters.append(AirViolation.event_date <= params.event_date_to)
        if params.last_hours is not None:
            cutoff = datetime.now(BEIRUT_TIMEZONE) - timedelta(hours=params.last_hours)
            event_time = func.coalesce(AirViolation.event_time, time.min)
            filters.append(
                (AirViolation.event_date > cutoff.date())
                | (
                    (AirViolation.event_date == cutoff.date())
                    & (event_time >= cutoff.time().replace(tzinfo=None))
                )
            )
        if params.caza_en:
            filters.append(AirViolation.caza_en.ilike(f"%{params.caza_en}%"))
        return filters
    def discard_for_message(self, message: RawMessage) -> None:
        existing = self.db.scalar(
            select(AirViolation).where(AirViolation.raw_message_id == message.id)
        )
        if existing is not None:
            self.db.delete(existing)
            self.db.flush()
            increment(AIR_VIOLATION_CACHE_VERSION_KEY)
