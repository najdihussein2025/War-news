"""
Phase 3 Step 0 investigation summary
------------------------------------
Extraction is persisted already. ExtractIncidentsAction calls
RawMessageRepository.save_extraction_result(), which serializes ExtractionResult
into raw_messages.extraction_result (JSONB). The stored object has village and
action_description mention text plus categories, casualties, model, and
extracted_at; save_extraction_result may also append an audited candidates list.
Therefore Phase 3 reuses extraction_result and does not add or alter extraction
storage. Only the separate raw_messages.match_result column is added.
"""

from dataclasses import dataclass
from collections.abc import Callable

from app.core.text_normalization import normalize_arabic_text
from app.llm.dtos import ExtractionResult
from app.news.dtos import (
    MatchResultDTO,
    MatchResultStatus,
)
from app.news.interfaces import MatchingServiceInterface
from app.news.interfaces import (
    ConditionRepositoryInterface,
    VillageRepositoryInterface,
)
from app.news.models import (
    Condition,
    Village,
)

MATCH_THRESHOLD = 0.6
LOW_CONFIDENCE_THRESHOLD = 0.35
DEFAULT_CANDIDATE_LIMIT = 5

@dataclass(frozen=True)
class _ClassifiedMatch:
    matched_id: int | None
    confidence: float | None
    status: MatchResultStatus


class MatchingService(MatchingServiceInterface):
    def __init__(
        self,
        village_repository: VillageRepositoryInterface,
        condition_repository: ConditionRepositoryInterface,
        candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    ) -> None:
        if candidate_limit < 1:
            raise ValueError("candidate_limit must be at least 1")
        self.villages = village_repository
        self.conditions = condition_repository
        self.candidate_limit = candidate_limit

    def match(self, extraction_result: ExtractionResult) -> MatchResultDTO:
        village = self._match_mention(
            extraction_result.village,
            self.villages.find_similar,
        )
        condition = self._match_mention(
            extraction_result.action_description,
            self.conditions.find_similar,
        )
        return MatchResultDTO(
            matched_village_id=village.matched_id,
            village_confidence=village.confidence,
            village_match_status=village.status,
            village_review_required=village.status != MatchResultStatus.matched,
            raw_village_text=extraction_result.village,
            matched_condition_id=condition.matched_id,
            condition_confidence=condition.confidence,
            condition_match_status=condition.status,
            condition_review_required=condition.status != MatchResultStatus.matched,
            raw_condition_text=extraction_result.action_description,
        )

    def _match_mention(
        self,
        mention: str | None,
        find_similar: Callable[
            [str, int],
            list[tuple[Village, float]] | list[tuple[Condition, float]],
        ],
    ) -> _ClassifiedMatch:
        normalized = normalize_arabic_text(mention or "")
        if not normalized:
            return _ClassifiedMatch(None, None, MatchResultStatus.unmatched)

        candidates = find_similar(normalized, self.candidate_limit)
        if not candidates:
            return _ClassifiedMatch(None, None, MatchResultStatus.unmatched)

        candidate, score = candidates[0]
        score = max(0.0, min(float(score), 1.0))
        if score >= MATCH_THRESHOLD:
            return _ClassifiedMatch(candidate.id, score, MatchResultStatus.matched)
        if score >= LOW_CONFIDENCE_THRESHOLD:
            return _ClassifiedMatch(
                candidate.id,
                score,
                MatchResultStatus.matched_low_confidence,
            )
        return _ClassifiedMatch(None, score, MatchResultStatus.unmatched)
