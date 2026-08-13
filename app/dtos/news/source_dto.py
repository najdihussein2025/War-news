from pydantic import BaseModel, ConfigDict

from app.models.news import SourceType


class SourceListItemDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: SourceType
    name: str
    is_active: bool
