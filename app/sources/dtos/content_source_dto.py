from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ContentSourceListItemDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    source_platform: str
    source_name: str
    origin_account: str
    message_count: int
    last_seen: datetime
    first_seen: datetime
    is_blocked: bool = False


class ContentSourceRecentMessageDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: int
    raw_text: str | None
    message_datetime: datetime | None
    received_at: datetime


class ContentSourceDetailDTO(ContentSourceListItemDTO):
    recent_messages: list[ContentSourceRecentMessageDTO]


class ContentSourceFilterData(BaseModel):
    model_config = ConfigDict(frozen=True)

    platform: str | None = None
    search: str | None = None


class ContentSourceBlockUpdateData(BaseModel):
    model_config = ConfigDict(frozen=True)

    is_blocked: bool


class ContentSourceBlockDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    source_platform: str
    origin_account: str
    is_blocked: bool
    blocked_at: datetime | None
    blocked_by: UUID | None
