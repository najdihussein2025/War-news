from datetime import date, datetime, time
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class IncidentListItemDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID | None
    raw_message_id: int
    raw_status: str
    village: str | None
    condition: str | None
    event_date: date
    event_time: time | None = None
    khabar: str
    source: str | None
    source_reference: str | None
    matched: bool
    duplicate_flag: Literal["none", "possible"]
    duplicate_level: Literal["low", "medium", "high"] | None = None
    duplicate_similarity_score: float | None = None
    details_pending: bool
    created_at: datetime
    version: int = 1
    locked_by_user_id: UUID | None = None
    edit_lock_expires_at: datetime | None = None


class IncidentListParams(BaseModel):
    model_config = ConfigDict(frozen=True)

    limit: int = Field(default=150, ge=1, le=150)
    offset: int = Field(default=0, ge=0)
    village: str | None = None
    condition: str | None = None
    source_type: str | None = None
    event_date_from: date | None = None
    event_date_to: date | None = None
    flagged_only: bool = False
    verification_status: Literal["matched", "needs_verification"] | None = None
    duplicate_only: bool = False
    sort_order: Literal["newest", "oldest"] = "newest"


class IncidentListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[IncidentListItemDTO]
    total: int
    limit: int
    offset: int
    latest_incident_at: datetime | None = None


class CasualtyDemographicsDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    male_d: int | None
    male_i: int | None
    female_d: int | None
    female_i: int | None
    children_d: int | None
    children_i: int | None


class IncidentVillageDetailDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    acs_code: int
    acs_name: str | None
    cad_name: str | None
    ref_name_en: str | None
    ref_name_ar: str | None
    caza_en: str | None
    caza_ar: str | None
    mohafaza_en: str | None
    mohafaza_ar: str | None
    coord_x: float | None
    coord_y: float | None


class IncidentCategorySectionDTO(BaseModel):
    """Flat incident_details fields for one UI category section."""

    model_config = ConfigDict(extra="allow", frozen=True)


class IncidentDetailDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    village: str | None
    village_details: IncidentVillageDetailDTO | None = None
    condition: str | None
    source: str | None
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
    version: int = 1
    locked_by_user_id: UUID | None = None
    edit_lock_expires_at: datetime | None = None
    matched: bool
    duplicate_flag: Literal["none", "possible"]
    duplicate_level: Literal["low", "medium", "high"] | None = None
    duplicate_similarity_score: float | None = None
    casualty_demographics: CasualtyDemographicsDTO
    lebanese_army: IncidentCategorySectionDTO | None = None
    unifil: IncidentCategorySectionDTO | None = None
    municipality: IncidentCategorySectionDTO | None = None
    school_university: IncidentCategorySectionDTO | None = None
    religious_cultural: IncidentCategorySectionDTO | None = None
    hospital: IncidentCategorySectionDTO | None = None
    health_center: IncidentCategorySectionDTO | None = None
    emergency_civil_defense: IncidentCategorySectionDTO | None = None
    press: IncidentCategorySectionDTO | None = None
    government_building: IncidentCategorySectionDTO | None = None
    road_bridge: IncidentCategorySectionDTO | None = None
    vehicles: IncidentCategorySectionDTO | None = None
    crossings_other: IncidentCategorySectionDTO | None = None
    warning_classification: IncidentCategorySectionDTO | None = None


class IncidentUpdateDTO(BaseModel):
    version: int = Field(ge=1)
    event_date: date
    event_time: time | None = None
    khabar: str = Field(min_length=1)
    note: str | None = None
    worker_name: str | None = None
    source_link: str | None = None
    source_link_2: str | None = None
    total_deaths: int | None = Field(default=None, ge=0)
    total_injuries: int | None = Field(default=None, ge=0)
    deaths: int | None = Field(default=None, ge=0)
    injuries: int | None = Field(default=None, ge=0)


class IncidentCreateDTO(BaseModel):
    village: str = Field(min_length=1)
    condition: str = Field(min_length=1)
    event_date: date
    event_time: time | None = None
    khabar: str = Field(min_length=1)
    note: str | None = None
    source_link: str | None = None


class IncidentDetailsPatchDTO(BaseModel):
    """Partial incident_details update keyed by API field names."""

    model_config = ConfigDict(extra="forbid")

    fields: dict[str, Any] = Field(min_length=1)
    version: int = Field(ge=1)

    @field_validator("fields")
    @classmethod
    def fields_must_not_be_empty(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("At least one field must be provided.")
        return value


class DuplicateCandidateIncidentDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    village: str | None
    condition: str | None
    event_date: date
    event_time: time | None
    khabar: str
    source: str | None
    source_reference: str | None
    total_deaths: int | None
    total_injuries: int | None


class IncidentDuplicateCandidateDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    match_id: int
    similarity_score: float
    level: Literal["medium"] = "medium"
    status: Literal["pending"] = "pending"
    candidate: DuplicateCandidateIncidentDTO


class IncidentDuplicateResolutionDTO(BaseModel):
    match_id: int
    decision: Literal["confirmed_duplicate", "false_positive"]
    version: int = Field(ge=1)


class IncidentDuplicateResolutionResultDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision: Literal["confirmed_duplicate", "false_positive"]
    incident_id: UUID
    canonical_incident_id: UUID
