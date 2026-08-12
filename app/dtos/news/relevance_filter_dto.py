from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class RelevanceConfidence(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class RelevanceClassificationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    is_relevant: bool | None
    confidence: RelevanceConfidence | None
    reason: str
    model: str
    classified_at: datetime
    parse_error: str | None = None


class RelevancePolicyVerdict(str, Enum):
    reject = "reject"
    proceed = "proceed"
    uncertain = "uncertain"


class RelevancePolicyResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    verdict: RelevancePolicyVerdict
    status: str
    low_confidence_relevance: bool


class FilterPendingMessagesData(BaseModel):
    model_config = ConfigDict(frozen=True)

    batch_size: int = Field(default=200, ge=1)


class FilterBatchSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    processed: int
    relevant: int
    rejected: int
    uncertain: int
    errored: int
    auto_rejected_by_keyword: int
    classifier_calls_made: int
