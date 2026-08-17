from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class IngestionLogFilterData(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_id: int | None = None
    status: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=100, ge=1, le=100)


class IngestionLogItemDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    source_id: int
    source_name: str
    run_timestamp: datetime
    started_at: datetime | None
    finished_at: datetime | None
    duration_seconds: int | None
    messages_fetched: int
    messages_parsed: int
    messages_flagged: int
    messages_failed: int
    messages_blocked: int
    status: str
    error_message: str | None
    retry_of_id: int | None


class IngestionLogPageDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[IngestionLogItemDTO]
    total: int
    page: int
    page_size: int
