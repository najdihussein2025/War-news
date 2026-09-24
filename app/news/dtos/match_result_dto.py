from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

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
    matched_condition_id: int | None = None
    condition_confidence: float | None = None
    condition_match_status: MatchResultStatus | None = None
    condition_review_required: bool | None = None
    raw_condition_text: str | None = None
    condition_review_reason: str | None = None
    condition_action_source: str | None = None
    source_condition_text: str | None = None
    event_index: int | None = None
    event_location_count: int | None = None
    qualifier_text: str | None = None
    alias_matched: bool = False
    resolved_by_geo_context: bool = False
    geo_context_anchor_village_id: int | None = None
    original_top_candidate_id: int | None = None
    alternate_candidate_village_id: int | None = None


class SubEventMatchResult(BaseModel):
    """Condition match for one extracted sub-event inside a bulletin."""

    model_config = ConfigDict(frozen=True)

    index: int
    action_description: str | None
    evidence_span: str | None
    matched_condition_id: int | None
    condition_confidence: float | None
    condition_match_status: MatchResultStatus
    condition_review_required: bool
    condition_review_reason: str | None = None
    condition_action_source: str | None = None
    source_condition_text: str | None = None


class MatchResultDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    # Per-village results — one entry per input village string.
    village_matches: list[VillageMatchResult]

    # Denormalised flag stored at the top level so that the DB-level
    # low-confidence query (RawMessage.match_result["any_village_low_confidence"])
    # stays simple and backward-compatible.
    any_village_low_confidence: bool
    location_ambiguity: bool = False
    location_alternatives: list[str] = Field(default_factory=list)
    location_ambiguity_evidence: str | None = None

    matched_condition_id: int | None
    condition_confidence: float | None
    condition_match_status: MatchResultStatus
    condition_review_required: bool
    raw_condition_text: str | None
    condition_review_reason: str | None = None
    condition_action_source: str | None = None
    source_condition_text: str | None = None
    sub_event_matches: list[SubEventMatchResult] = Field(default_factory=list)
