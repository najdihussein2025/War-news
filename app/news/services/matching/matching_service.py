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
from math import hypot

from app.core.config import settings
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


@dataclass(frozen=True)
class _VillageCandidateResolution:
    candidates: tuple[tuple[Village, float], ...]
    classified: _ClassifiedMatch
    alias_hit: bool = False
    collision_like: bool = False


@dataclass(frozen=True)
class _GeoResolution:
    classified: _ClassifiedMatch
    resolved_by_geo_context: bool = False
    anchor_village_id: int | None = None
    original_top_candidate_id: int | None = None
    alternate_candidate_village_id: int | None = None


class MatchingService(MatchingServiceInterface):
    def __init__(
        self,
        village_repository: VillageRepositoryInterface,
        condition_repository: ConditionRepositoryInterface,
        candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
        geo_context_max_distance_meters: float | None = None,
        geo_context_min_distance_advantage_meters: float | None = None,
    ) -> None:
        if candidate_limit < 1:
            raise ValueError("candidate_limit must be at least 1")
        self.villages = village_repository
        self.conditions = condition_repository
        self.candidate_limit = candidate_limit
        self.geo_context_max_distance_meters = (
            float(settings.village_geo_context_max_distance_meters)
            if geo_context_max_distance_meters is None
            else float(geo_context_max_distance_meters)
        )
        self.geo_context_min_distance_advantage_meters = (
            float(settings.village_geo_context_min_distance_advantage_meters)
            if geo_context_min_distance_advantage_meters is None
            else float(geo_context_min_distance_advantage_meters)
        )

    def match(self, extraction_result: ExtractionResult) -> MatchResultDTO:
        village_mentions = self._village_mentions(extraction_result)
        candidate_resolutions = [
            self._resolve_village_candidates(mention.village)
            for mention in village_mentions
        ]
        anchors = [
            resolution.candidates[0][0]
            for resolution in candidate_resolutions
            if self._is_anchor(resolution)
        ]
        village_matches: list[VillageMatchResult] = []
        for village_mention, resolution in zip(
            village_mentions,
            candidate_resolutions,
            strict=True,
        ):
            village_text = village_mention.village
            geo_resolution = self._resolve_with_geo_context(
                resolution,
                anchors,
            )
            classified = geo_resolution.classified
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
                    resolved_by_geo_context=(
                        geo_resolution.resolved_by_geo_context
                    ),
                    geo_context_anchor_village_id=(
                        geo_resolution.anchor_village_id
                    ),
                    original_top_candidate_id=(
                        geo_resolution.original_top_candidate_id
                    ),
                    alternate_candidate_village_id=(
                        geo_resolution.alternate_candidate_village_id
                    ),
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

    def _resolve_village_candidates(
        self,
        mention: str | None,
    ) -> _VillageCandidateResolution:
        normalized = normalize_arabic_text(mention or "")
        if not normalized:
            return _VillageCandidateResolution(
                (),
                _ClassifiedMatch(None, None, MatchResultStatus.unmatched),
            )

        resolve_alias = getattr(self.villages, "resolve_alias", None)
        if resolve_alias is not None:
            alias_hit = resolve_alias(normalized)
            if alias_hit is not None:
                village, score = alias_hit
                confidence = max(0.0, min(float(score), 1.0))
                return _VillageCandidateResolution(
                    ((village, confidence),),
                    _ClassifiedMatch(
                        village.id,
                        confidence,
                        MatchResultStatus.matched,
                    ),
                    alias_hit=True,
                )

        candidates = tuple(
            (candidate, max(0.0, min(float(score), 1.0)))
            for candidate, score in self.villages.find_similar(
                normalized,
                self.candidate_limit,
            )
        )
        classified = self._classify_candidates(candidates, normalized)
        collision_like = self._has_collision_like_alternative(
            normalized,
            candidates,
        )
        if (
            collision_like
            and classified.status == MatchResultStatus.matched
        ):
            classified = _ClassifiedMatch(
                classified.matched_id,
                classified.confidence,
                MatchResultStatus.matched_low_confidence,
            )
        return _VillageCandidateResolution(
            candidates,
            classified,
            collision_like=collision_like,
        )

    @staticmethod
    def _has_collision_like_alternative(
        normalized_mention: str,
        candidates: tuple[tuple[Village, float], ...],
    ) -> bool:
        if len(candidates) < 2:
            return False
        mention = normalize_arabic_text(normalized_mention)
        matching_candidates = 0
        for candidate, score in candidates:
            if score < LOW_CONFIDENCE_THRESHOLD:
                continue
            reference = normalize_arabic_text(
                getattr(candidate, "ref_name_ar", None) or ""
            )
            if reference == mention or reference.startswith(f"{mention} "):
                matching_candidates += 1
        return matching_candidates >= 2

    @staticmethod
    def _is_anchor(resolution: _VillageCandidateResolution) -> bool:
        return (
            resolution.alias_hit
            or (
                resolution.classified.status == MatchResultStatus.matched
                and not resolution.collision_like
            )
        ) and bool(resolution.candidates)

    def _resolve_with_geo_context(
        self,
        resolution: _VillageCandidateResolution,
        anchors: list[Village],
    ) -> _GeoResolution:
        classified = resolution.classified
        alternate_id = self._alternate_candidate_id(resolution)
        fallback = _GeoResolution(
            classified,
            alternate_candidate_village_id=alternate_id,
        )
        if self._is_anchor(resolution) or not anchors or not resolution.candidates:
            return fallback

        eligible = [
            (candidate, score)
            for candidate, score in resolution.candidates
            if score >= LOW_CONFIDENCE_THRESHOLD
            and getattr(candidate, "coord_x", None) is not None
            and getattr(candidate, "coord_y", None) is not None
        ]
        if len(eligible) < 2:
            return fallback

        original = resolution.candidates[0][0]
        if (
            getattr(original, "coord_x", None) is None
            or getattr(original, "coord_y", None) is None
        ):
            return fallback

        original_distance, _ = self._nearest_anchor(original, anchors)
        best_candidate, best_score = eligible[0]
        best_distance, best_anchor = self._nearest_anchor(
            best_candidate,
            anchors,
        )
        for candidate, score in eligible[1:]:
            distance, anchor = self._nearest_anchor(candidate, anchors)
            if distance < best_distance:
                best_candidate = candidate
                best_score = score
                best_distance = distance
                best_anchor = anchor

        if (
            best_candidate.id == original.id
            or best_distance > self.geo_context_max_distance_meters
            or (
                original_distance - best_distance
                < self.geo_context_min_distance_advantage_meters
            )
        ):
            return fallback

        return _GeoResolution(
            _ClassifiedMatch(
                best_candidate.id,
                best_score,
                MatchResultStatus.matched,
            ),
            resolved_by_geo_context=True,
            anchor_village_id=best_anchor.id,
            original_top_candidate_id=original.id,
            alternate_candidate_village_id=original.id,
        )

    @staticmethod
    def _alternate_candidate_id(
        resolution: _VillageCandidateResolution,
    ) -> int | None:
        if (
            resolution.classified.status
            != MatchResultStatus.matched_low_confidence
            or len(resolution.candidates) < 2
        ):
            return None
        if not resolution.collision_like:
            return resolution.candidates[1][0].id

        top_reference = normalize_arabic_text(
            getattr(resolution.candidates[0][0], "ref_name_ar", None) or ""
        )
        for candidate, score in resolution.candidates[1:]:
            reference = normalize_arabic_text(
                getattr(candidate, "ref_name_ar", None) or ""
            )
            if score >= LOW_CONFIDENCE_THRESHOLD and (
                reference == top_reference
                or reference.startswith(f"{top_reference} ")
                or top_reference.startswith(f"{reference} ")
            ):
                return candidate.id
        return resolution.candidates[1][0].id

    @staticmethod
    def _nearest_anchor(
        village: Village,
        anchors: list[Village],
    ) -> tuple[float, Village]:
        distances = [
            (
                hypot(
                    float(village.coord_x) - float(anchor.coord_x),
                    float(village.coord_y) - float(anchor.coord_y),
                ),
                anchor,
            )
            for anchor in anchors
            if getattr(anchor, "coord_x", None) is not None
            and getattr(anchor, "coord_y", None) is not None
        ]
        if not distances:
            return float("inf"), anchors[0]
        return min(distances, key=lambda item: item[0])

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

        candidates = tuple(
            (candidate, max(0.0, min(float(score), 1.0)))
            for candidate, score in find_similar(
                normalized,
                self.candidate_limit,
            )
        )
        return self._classify_candidates(candidates, normalized)

    def _classify_candidates(
        self,
        candidates: tuple[
            tuple[Village | Condition, float],
            ...,
        ],
        normalized: str,
    ) -> _ClassifiedMatch:
        if not candidates:
            return _ClassifiedMatch(None, None, MatchResultStatus.unmatched)
        allowed: list[tuple[Village | Condition, float]] = []
        for candidate, score in candidates:
            if not self._condition_match_allowed(candidate.id, normalized):
                continue
            allowed.append((candidate, score))
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
