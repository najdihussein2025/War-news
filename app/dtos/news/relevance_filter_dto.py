from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.dtos.news.classification_result_dto import ClassificationResultDTO


class RelevancePolicyVerdict(str, Enum):
    reject = "reject"
    proceed = "proceed"
    uncertain = "uncertain"


class RelevancePolicyResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    verdict: RelevancePolicyVerdict
    status: str
    needs_review: bool


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


RelevanceClassificationResult = ClassificationResultDTO
