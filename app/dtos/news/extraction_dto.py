from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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


class ExtractionResult(BaseModel):
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
    incidents_created: int
    incidents_merged: int
    incidents_flagged_duplicate: int
    candidates_unmatched_village: int
    candidates_invalid_action: int
    errored: int
