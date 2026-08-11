from datetime import datetime

from pydantic import BaseModel, Field


class ExtractedCandidate(BaseModel):
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
    candidates: list[ExtractedCandidate]
    model: str
    extracted_at: datetime


class ExtractionBatchSummary(BaseModel):
    processed: int
    incidents_created: int
    incidents_merged: int
    incidents_flagged_duplicate: int
    candidates_unmatched_village: int
    candidates_invalid_action: int
    errored: int
