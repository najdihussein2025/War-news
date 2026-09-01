from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LoginLogFilterData(BaseModel):
    model_config = ConfigDict(frozen=True)

    search: str | None = None
    success: bool | None = True
    date_from: date | None = None
    date_to: date | None = None
    created_after: datetime | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=25, ge=1, le=100)


class LoginLogItemDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    username: str
    success: bool
    ip: str
    timestamp: datetime


class LoginLogPageDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[LoginLogItemDTO]
    total: int
    page: int
    page_size: int
