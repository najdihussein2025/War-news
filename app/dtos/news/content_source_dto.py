from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ContentSourceListItemDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    source_platform: str
    source_name: str
    message_count: int
    last_seen: datetime


class ContentSourceFilterData(BaseModel):
    model_config = ConfigDict(frozen=True)

    platform: str | None = None
    search: str | None = None
