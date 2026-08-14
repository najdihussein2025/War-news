from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field


class AirViolationDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: int
    raw_message_id: int | None
    condition_id: int
    source_id: int
    caza_en: str | None
    caza_ar: str | None
    event_month: str | None
    event_date: date
    event_time: time | None
    khabar: str
    note_1: str | None
    note_2: str | None
    source_link: str | None
    created_at: datetime
    action_en: str
    action_ar: str
    source_name: str


class AirViolationListParams(BaseModel):
    model_config = ConfigDict(frozen=True)

    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    condition_id: int | None = None
    event_date_from: date | None = None
    event_date_to: date | None = None
    caza_en: str | None = None


class AirViolationListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[AirViolationDTO]
    total: int
    limit: int
    offset: int
