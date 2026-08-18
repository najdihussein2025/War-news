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
from app.news.dtos.match_result_dto import VillageMatchResult
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
CONDITION_DISTINGUISHING_TOKENS: dict[int, tuple[str, ...]] = {
    2: ("تحذيريه",),
    39: ("وهميه",),
}

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
        village_list = extraction_result.village or []
        village_matches: list[VillageMatchResult] = []
        for village_text in village_list:
            classified = self._match_mention(village_text, self.villages.find_similar)
            village_matches.append(
                VillageMatchResult(
                    matched_village_id=classified.matched_id,
                    village_confidence=classified.confidence,
                    village_match_status=classified.status,
                    village_review_required=classified.status != MatchResultStatus.matched,
                    raw_village_text=village_text,
                )
            )

        any_village_low_confidence = any(
            vm.village_match_status == MatchResultStatus.matched_low_confidence
            for vm in village_matches
        )

        condition = self._match_mention(
            extraction_result.action_description,
            self.conditions.find_similar,
        )
        return MatchResultDTO(
            village_matches=village_matches,
            any_village_low_confidence=any_village_low_confidence,
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

        for candidate, score in candidates:
            if not self._condition_match_allowed(candidate.id, normalized):
                continue
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

        return _ClassifiedMatch(None, None, MatchResultStatus.unmatched)

    @staticmethod
    def _condition_match_allowed(condition_id: int, normalized_text: str) -> bool:
        required_tokens = CONDITION_DISTINGUISHING_TOKENS.get(condition_id)
        if required_tokens is None:
            return True
        return any(token in normalized_text for token in required_tokens)
