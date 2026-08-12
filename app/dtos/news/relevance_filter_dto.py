from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RelevanceClassificationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    relevant: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    model: str
    classified_at: datetime


class FilterPendingMessagesData(BaseModel):
    model_config = ConfigDict(frozen=True)

    batch_size: int = Field(default=200, ge=1)


class FilterBatchSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    processed: int
    relevant: int
    rejected: int
    errored: int
    auto_rejected_by_keyword: int
    classifier_calls_made: int
