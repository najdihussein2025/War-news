from datetime import date, datetime, time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AirViolationVillageDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    village_id: int | None
    name: str


class AirViolationWindowReportDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    event_date: date
    event_time: time | None = None
    khabar: str
    source_name: str
    source_link: str | None = None
    villages: list[AirViolationVillageDTO] = Field(default_factory=list)


class AirViolationDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: int
    raw_message_id: int | None
    condition_id: int
    source_id: int
    village_id: int | None = None
    caza_en: str | None
    caza_ar: str | None
    village_en: str | None = None
    village_ar: str | None = None
    villages: list[AirViolationVillageDTO] = Field(default_factory=list)
    event_month: str | None
    war_month: int | None = None
    event_date: date
    event_time: time | None
    window_id: str | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    window_violation_count: int | None = None
    window_duration_minutes: int | None = None
    window_reports: list[AirViolationWindowReportDTO] = Field(default_factory=list)
    # Breaches this row contributes: villages for helicopters, cazas for spy
    # balloons, 1 for a warplane/drone window.
    breach_count: int | None = None
    unit_type: str | None = None
    khabar: str
    note_1: str | None
    note_2: str | None
    source_link: str | None
    version: int
    locked_by_user_id: UUID | None = None
    edit_lock_expires_at: datetime | None = None
    created_at: datetime
    action_en: str
    action_ar: str
    source_name: str
    is_imported: bool = False
    import_filename: str | None = None
    import_row: dict | None = None
    import_enrichment: dict | None = None


class AirViolationCreateDTO(BaseModel):
    condition_id: int
    caza_en: str = Field(min_length=1)
    caza_ar: str | None = None
    event_date: date
    event_time: time | None = None
    khabar: str = Field(min_length=1)
    note_1: str | None = None
    note_2: str | None = None
    source_link: str | None = None


class AirViolationUpdateDTO(AirViolationCreateDTO):
    version: int = Field(ge=1)


class AirViolationListParams(BaseModel):
    model_config = ConfigDict(frozen=True)

    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    condition_id: int | None = None
    imported_only: bool = False
    event_date_from: date | None = None
    event_date_to: date | None = None
    caza_en: str | None = None
    village: str | None = None
    last_hours: int | None = Field(default=None, ge=1, le=8760)
    sort_order: Literal["newest", "oldest"] = "newest"


class AirViolationListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[AirViolationDTO]
    total: int
    limit: int
    offset: int


class AirViolationWindowDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    condition_id: int | None = None
    unit_type: str | None = None
    caza_en: str
    caza_ar: str | None = None
    window_start: datetime
    window_end: datetime
    window_duration_minutes: int | None = None
    violation_count: int
    villages: list[AirViolationVillageDTO] = Field(default_factory=list)


class AirViolationWindowListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[AirViolationWindowDTO]
    total: int
    limit: int
    offset: int


class AirViolationSummaryDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    warplanes: int
    surveillance_aircraft: int
    helicopters: int
    spy_balloons: int = 0
