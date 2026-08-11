from datetime import datetime

from pydantic import BaseModel, Field


class RelevanceClassificationResult(BaseModel):
    relevant: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    model: str
    classified_at: datetime


class FilterBatchSummary(BaseModel):
    processed: int
    relevant: int
    rejected: int
    errored: int
    auto_rejected_by_keyword: int
    gemini_calls_made: int
