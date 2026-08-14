from enum import Enum

from pydantic import BaseModel, ConfigDict


class MatchResultStatus(str, Enum):
    matched = "matched"
    matched_low_confidence = "matched_low_confidence"
    unmatched = "unmatched"


class MatchResultDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    matched_village_id: int | None
    village_confidence: float | None
    village_match_status: MatchResultStatus
    village_review_required: bool
    raw_village_text: str | None

    matched_condition_id: int | None
    condition_confidence: float | None
    condition_match_status: MatchResultStatus
    condition_review_required: bool
    raw_condition_text: str | None
