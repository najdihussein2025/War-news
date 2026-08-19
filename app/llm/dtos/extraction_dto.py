from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ExtractionCategoryKey(str, Enum):
    casualty_demographics = "casualty_demographics"
    lebanese_army = "lebanese_army"
    unifil = "unifil"
    municipality = "municipality"
    school_university = "school_university"
    religious_cultural = "religious_cultural"
    hospital = "hospital"
    health_center = "health_center"
    emergency_civil_defense = "emergency_civil_defense"
    press = "press"
    government_building = "government_building"
    road_bridge = "road_bridge"
    vehicles = "vehicles"
    crossings_other = "crossings_other"
    warning_classification = "warning_classification"


class DidValue(str, Enum):
    direct = "D"
    indirect = "ID"


class ExtractionCasualties(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_deaths: int | None = None
    total_injuries: int | None = None
    deaths: int | None = None
    injuries: int | None = None
    male_deaths: int | None = None
    male_injuries: int | None = None
    female_deaths: int | None = None
    female_injuries: int | None = None
    children_deaths: int | None = None
    children_injuries: int | None = None


class ExtractionCategory(BaseModel):
    model_config = ConfigDict(frozen=True)

    did: DidValue | None = None
    name: str | None = None
    casualties: ExtractionCasualties | None = None


class ExtractionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    is_relevant: bool
    village: list[str] | None = None
    action_description: str | None = None

    @field_validator("village", mode="before")
    @classmethod
    def _coerce_village(cls, v: object) -> list[str] | None:
        """Accept old-shape strings (stored before Task-4 migration) and coerce to list."""
        if v is None:
            return None
        if isinstance(v, str):
            parts = [p.strip() for p in v.split(",") if p.strip()]
            return parts if parts else None
        return v
    categories: dict[ExtractionCategoryKey, ExtractionCategory] = Field(
        default_factory=dict
    )
    casualties: ExtractionCasualties = Field(default_factory=ExtractionCasualties)
    # Tier 1 stores presence-gate keys here; category detail fills `categories` in Tier 2.
    presence_category_keys: list[ExtractionCategoryKey] = Field(default_factory=list)
    # 1 = fast path (general fields only); 2 = full category detail complete.
    extraction_tier: int = Field(default=1, ge=1, le=2)
    model: str
    extracted_at: datetime

    @model_validator(mode="before")
    @classmethod
    def _infer_legacy_extraction_tier(cls, data: object) -> object:
        """Legacy rows omit extraction_tier; infer from stored category detail."""
        if not isinstance(data, dict):
            return data
        if data.get("extraction_tier") is not None:
            return data
        categories = data.get("categories") or {}
        inferred_tier = 2 if categories else 1
        return {**data, "extraction_tier": inferred_tier}


class ExtractedCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    location_text: str
    action_en: str
    deaths: int | None
    injuries: int | None
    male_d: int | None
    male_i: int | None
    female_d: int | None
    female_i: int | None
    children_d: int | None
    children_i: int | None
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


class CandidateExtractionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidates: list[ExtractedCandidate]
    model: str
    extracted_at: datetime


class ExtractPendingMessagesData(BaseModel):
    model_config = ConfigDict(frozen=True)

    batch_size: int = Field(default=50, ge=1)


class ExtractionBatchSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    processed: int
    extracted: int
    errored: int
