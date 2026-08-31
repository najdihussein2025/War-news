from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class MapEventDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    event_type: Literal["incident", "air_violation"]
    category: str
    title: str
    summary: str
    occurred_at: datetime
    latitude: float
    longitude: float
    village: str | None = None
    caza: str | None = None
    source: str | None = None
    detail_path: str | None = None


class MapEventResponseDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[MapEventDTO]
    unmapped_count: int
    truncated: bool
