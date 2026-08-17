from datetime import date, datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

class AuditLogFilterData(BaseModel):
    model_config = ConfigDict(frozen=True)
    search: str | None = None
    action: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=100, ge=1, le=100)

class AuditLogItemDTO(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: UUID
    action: str
    performed_by: str
    actor_id: UUID | None
    target_type: str
    target: str
    ip: str | None
    old_values: dict | None
    new_values: dict | None
    timestamp: datetime

class AuditLogPageDTO(BaseModel):
    model_config = ConfigDict(frozen=True)
    items: list[AuditLogItemDTO]
    total: int
    page: int
    page_size: int
