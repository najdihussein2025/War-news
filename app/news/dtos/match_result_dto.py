from enum import Enum

from pydantic import BaseModel, ConfigDict

from app.llm.dtos import VillageRole


class MatchResultStatus(str, Enum):
    matched = "matched"
    matched_low_confidence = "matched_low_confidence"
    unmatched = "unmatched"


class VillageMatchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    matched_village_id: int | None
    village_confidence: float | None
    village_match_status: MatchResultStatus
    village_review_required: bool
    raw_village_text: str | None
    village_role: VillageRole = VillageRole.target
    deaths: int | None = None
    injuries: int | None = None
    evidence_span: str | None = None
    resolved_by_geo_context: bool = False
    geo_context_anchor_village_id: int | None = None
    original_top_candidate_id: int | None = None
    alternate_candidate_village_id: int | None = None


class MatchResultDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    # Per-village results — one entry per input village string.
    village_matches: list[VillageMatchResult]

    # Denormalised flag stored at the top level so that the DB-level
    # low-confidence query (RawMessage.match_result["any_village_low_confidence"])
    # stays simple and backward-compatible.
    any_village_low_confidence: bool

    matched_condition_id: int | None
    condition_confidence: float | None
    condition_match_status: MatchResultStatus
    condition_review_required: bool
    raw_condition_text: str | None
