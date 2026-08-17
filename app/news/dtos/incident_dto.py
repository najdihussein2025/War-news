from datetime import date, datetime, time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class IncidentListItemDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    village: str | None
    condition: str
    event_date: date
    khabar: str
    source: str
    source_reference: str | None
    matched: bool
    duplicate_flag: Literal["none", "possible"]
    created_at: datetime


class IncidentListParams(BaseModel):
    model_config = ConfigDict(frozen=True)

    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    village: str | None = None
    source_type: str | None = None
    event_date_from: date | None = None
    event_date_to: date | None = None
    flagged_only: bool = False


class IncidentListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[IncidentListItemDTO]
    total: int
    limit: int
    offset: int


class CasualtyDemographicsDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    male_d: int | None
    male_i: int | None
    female_d: int | None
    female_i: int | None
    children_d: int | None
    children_i: int | None


class IncidentDetailDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    village: str | None
    condition: str
    source: str
    source_reference: str | None
    khabar: str
    note: str | None
    moh: str | None
    martyrs: str | None
    worker_name: str | None
    source_link: str | None
    source_link_2: str | None
    total_deaths: int | None
    total_injuries: int | None
    deaths: int | None
    injuries: int | None
    event_date: date
    event_time: time | None
    created_at: datetime
    matched: bool
    duplicate_flag: Literal["none", "possible"]
    casualty_demographics: CasualtyDemographicsDTO
    lebanese_army: None = None
    unifil: None = None
    municipality: None = None
    school_university: None = None
    religious_cultural: None = None
    hospital: None = None
    health_center: None = None
    emergency_civil_defense: None = None
    press: None = None
    government_building: None = None
    road_bridge: None = None
    vehicles: None = None
    crossings_other: None = None
    warning_classification: None = None
