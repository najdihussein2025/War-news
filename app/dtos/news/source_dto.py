from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.news import SourceType


class SourceListItemDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: int
    type: SourceType
    name: str
    is_active: bool
    last_message_at: datetime | None
    total_messages: int


class SourceDetailDTO(SourceListItemDTO):
    external_id: str | None
    created_at: datetime
    last_cursor: str | None


class SourceLookupData(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_id: int


class SourceActiveUpdateData(SourceLookupData):
    is_active: bool
