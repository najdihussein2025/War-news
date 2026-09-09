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
from app.llm.dtos import VillageRole, VillageRoleEntry
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
# Minimum score gap between #1 and #2 before a ≥0.6 hit is treated as a
# confident match. Recon showed five * النبطية villages tied at ~0.615 with
# margin 0.0 (lowest id won). Unambiguous hits like النبطية الفوقا had
# ~0.29 margin. 0.05 catches exact/near ties without demoting clear winners.
MATCH_TIE_MARGIN = 0.05
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
        village_mentions = self._village_mentions(extraction_result)
        village_matches: list[VillageMatchResult] = []
        for village_mention in village_mentions:
            village_text = village_mention.village
            classified = self._match_mention(
                village_text,
                self.villages.find_similar,
                allow_alias=True,
            )
            village_matches.append(
                VillageMatchResult(
                    matched_village_id=classified.matched_id,
                    village_confidence=classified.confidence,
                    village_match_status=classified.status,
                    village_review_required=classified.status != MatchResultStatus.matched,
                    raw_village_text=village_text,
                    village_role=village_mention.role,
                    deaths=village_mention.deaths,
                    injuries=village_mention.injuries,
                    evidence_span=village_mention.evidence_span,
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

    @staticmethod
    def _village_mentions(
        extraction_result: ExtractionResult,
    ) -> list[VillageRoleEntry]:
        if extraction_result.village_roles:
            return list(extraction_result.village_roles)
        return [
            VillageRoleEntry(village=village_text, role=VillageRole.target)
            for village_text in (extraction_result.village or [])
        ]

    def _match_mention(
        self,
        mention: str | None,
        find_similar: Callable[
            [str, int],
            list[tuple[Village, float]] | list[tuple[Condition, float]],
        ],
        *,
        allow_alias: bool = False,
    ) -> _ClassifiedMatch:
        normalized = normalize_arabic_text(mention or "")
        if not normalized:
            return _ClassifiedMatch(None, None, MatchResultStatus.unmatched)

        if allow_alias:
            resolve_alias = getattr(self.villages, "resolve_alias", None)
            if resolve_alias is not None:
                alias_hit = resolve_alias(normalized)
                if alias_hit is not None:
                    village, score = alias_hit
                    return _ClassifiedMatch(
                        village.id,
                        max(0.0, min(float(score), 1.0)),
                        MatchResultStatus.matched,
                    )

        candidates = find_similar(normalized, self.candidate_limit)
        if not candidates:
            return _ClassifiedMatch(None, None, MatchResultStatus.unmatched)

        allowed: list[tuple[Village | Condition, float]] = []
        for candidate, score in candidates:
            if not self._condition_match_allowed(candidate.id, normalized):
                continue
            allowed.append((candidate, max(0.0, min(float(score), 1.0))))
        if not allowed:
            return _ClassifiedMatch(None, None, MatchResultStatus.unmatched)

        top_candidate, top_score = allowed[0]
        second_score = allowed[1][1] if len(allowed) > 1 else None
        if top_score >= MATCH_THRESHOLD:
            if (
                second_score is not None
                and (top_score - second_score) < MATCH_TIE_MARGIN
            ):
                return _ClassifiedMatch(
                    top_candidate.id,
                    top_score,
                    MatchResultStatus.matched_low_confidence,
                )
            return _ClassifiedMatch(
                top_candidate.id,
                top_score,
                MatchResultStatus.matched,
            )
        if top_score >= LOW_CONFIDENCE_THRESHOLD:
            return _ClassifiedMatch(
                top_candidate.id,
                top_score,
                MatchResultStatus.matched_low_confidence,
            )
        return _ClassifiedMatch(None, top_score, MatchResultStatus.unmatched)

    @staticmethod
    def _condition_match_allowed(condition_id: int, normalized_text: str) -> bool:
        required_tokens = CONDITION_DISTINGUISHING_TOKENS.get(condition_id)
        if required_tokens is None:
            return True
        return any(token in normalized_text for token in required_tokens)
