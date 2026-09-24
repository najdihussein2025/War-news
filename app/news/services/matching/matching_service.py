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
import re

from app.core.config import settings
from app.core.llm_knowledge.loader import load_terminology
from app.core.text_normalization import normalize_arabic_text
from app.llm.dtos import ExtractionResult
from app.llm.dtos import VillageRole, VillageRoleEntry
from app.news.dtos import (
    MatchResultDTO,
    MatchResultStatus,
)
from app.news.dtos.match_result_dto import SubEventMatchResult, VillageMatchResult
from app.news.interfaces import MatchingServiceInterface
from app.news.interfaces import (
    ConditionRepositoryInterface,
    VillageRepositoryInterface,
)
from app.news.models import (
    Condition,
    Village,
)
from app.news.services.matching.conflict_attribution import (
    has_conflict_attribution_text,
)

MATCH_THRESHOLD = 0.6
LOW_CONFIDENCE_THRESHOLD = 0.35
# Minimum score gap between #1 and #2 before a ≥0.6 hit is treated as a
# confident match. Recon showed five * النبطية villages tied at ~0.615 with
# margin 0.0 (lowest id won). Unambiguous hits like النبطية الفوقا had
# ~0.29 margin. 0.05 catches exact/near ties without demoting clear winners.
MATCH_TIE_MARGIN = 0.05
DEFAULT_CANDIDATE_LIMIT = 5


def _contains_token_sequence(haystack: list[str], needle: list[str]) -> bool:
    if not haystack or not needle or len(needle) > len(haystack):
        return False
    return any(
        haystack[index : index + len(needle)] == needle
        for index in range(0, len(haystack) - len(needle) + 1)
    )


def _district_hint(text: str) -> str | None:
    normalized = normalize_arabic_text(text or "")
    match = re.search(r"(?:^|\s)قضاء\s+(.+)", normalized)
    if match is None:
        return None
    return re.split(r"[()،,;:.\-–—]", match.group(1), maxsplit=1)[0].strip() or None


def _strip_district_hint(text: str) -> str:
    marker = " قضاء "
    if marker not in text:
        return text
    return text.split(marker, 1)[0].strip() or text


def _distinguishing_tokens(meaning: str) -> tuple[str, ...]:
    return tuple(
        entry.term
        for entry in load_terminology("terminology/condition_labels.yaml")
        if entry.category == "distinguishing_token" and entry.meaning == meaning
    )


# Numeric IDs stay code-only (Phase 2.5). Arabic tokens load from terminology.
CONDITION_DISTINGUISHING_TOKENS: dict[int, tuple[str, ...]] = {
    2: _distinguishing_tokens("Warning Raid") or ("تحذيريه",),
    39: _distinguishing_tokens("Feigned Attacks") or ("وهميه",),
}

# Effect-defined conditions describe an outcome (fire, hole in the road, an
# explosion) that plain civilian/criminal/traffic news can also produce with
# no war attribution at all — condition_id 21 (Mining & Detonation) joined
# this set after the عباسية car-fire recon ("النيران تلتهم سيارة... حريق
# كبير") showed a civilian car fire matching Mining & Detonation with no
# conflict marker in the text. Reviewed the rest of Data/Conditions.json for
# the same failure mode and found no other gaps: Kidnapping/Arrest
# Operation/Ambushes read as war-context-only in this corpus's actual usage
# (no civilian-crime false positives observed), and every other condition is
# either device-defined (a named weapon/aircraft) rather than effect-defined,
# or explicitly scoped to require a prior Ground Incursion per its note.
EFFECT_DEFINED_CONDITION_IDS = frozenset({17, 21, 24, 25, 26, 27, 40})
EFFECT_DEFINED_CANONICAL_ACTIONS = {
    17: "shooting",
    21: "mining and detonation",
    24: "road blockage",
    25: "bulldozing",
    26: "cutting trees",
    27: "burning properties",
    40: "unexploded shells",
}
VILLAGE_MATCH_EXCEPTION_CATEGORIES = frozenset({"village_do_not_fuzzy_match"})
CONDITION_MATCH_EXCEPTION_CATEGORIES = frozenset(
    {"condition_do_not_match_without_attribution"}
)


def _exception_terms(
    relative_path: str,
    categories: frozenset[str],
) -> tuple[str, ...]:
    return tuple(
        normalize_arabic_text(entry.normalized or entry.term)
        for entry in load_terminology(relative_path)
        if entry.category in categories and (entry.normalized or entry.term)
    )


def _is_exception_match(text: str, exceptions: tuple[str, ...]) -> bool:
    normalized = normalize_arabic_text(text or "")
    if not normalized:
        return False
    return any(
        normalized == exception
        or exception in normalized
        or normalized in exception
        for exception in exceptions
    )


def _village_match_exceptions() -> tuple[str, ...]:
    return _exception_terms(
        "terminology/village_match_exceptions.yaml",
        VILLAGE_MATCH_EXCEPTION_CATEGORIES,
    )


def _condition_match_exceptions() -> tuple[str, ...]:
    return _exception_terms(
        "terminology/condition_match_exceptions.yaml",
        CONDITION_MATCH_EXCEPTION_CATEGORIES,
    )


@dataclass(frozen=True)
class _ClassifiedMatch:
    matched_id: int | None
    confidence: float | None
    status: MatchResultStatus


@dataclass(frozen=True)
class _ConditionResolution:
    match: _ClassifiedMatch
    review_required: bool
    review_reason: str | None = None
    action_source: str | None = "llm_text"
    source_condition_text: str | None = None


@dataclass(frozen=True)
class _VillageCandidateResolution:
    candidates: tuple[tuple[Village, float], ...]
    classified: _ClassifiedMatch
    alias_hit: bool = False
    collision_like: bool = False
    conditional_candidate_ids: frozenset[int] = frozenset()


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

    def match(
        self,
        extraction_result: ExtractionResult,
        *,
        cnrs_classification: dict | None = None,
    ) -> MatchResultDTO:
        root_condition = self._resolve_condition(
            extraction_result.action_description,
            source_hint=extraction_result.source_action_hint,
            action_source=extraction_result.action_source,
            cnrs_classification=cnrs_classification,
        )
        sub_event_matches = [
            self._match_sub_event(
                index,
                sub_event,
                cnrs_classification=cnrs_classification,
            )
            for index, sub_event in enumerate(extraction_result.sub_events)
        ]
        village_mentions = self._event_village_mentions(
            extraction_result,
            sub_event_matches,
            root_condition,
        )
        candidate_resolutions = [
            self._resolve_village_candidates(
                mention.village,
                qualifier_text=mention.qualifier_text,
            )
            for mention, _event_index, _event_size, _condition in village_mentions
        ]
        context_anchor_resolutions = [
            self._resolve_village_candidates(mention)
            for mention in self._context_anchor_mentions(
                extraction_result,
                village_mentions,
            )
        ]
        anchors = [
            resolution.candidates[0][0]
            for resolution in candidate_resolutions
            if self._is_anchor(resolution)
        ]
        anchors.extend(
            resolution.candidates[0][0]
            for resolution in context_anchor_resolutions
            if self._is_anchor(resolution) and resolution.candidates[0][1] >= 0.99
        )
        village_matches: list[VillageMatchResult] = []
        for (village_mention, event_index, event_size, condition), resolution in zip(
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
                    village_review_required=classified.status
                    != MatchResultStatus.matched,
                    raw_village_text=village_text,
                    village_role=village_mention.role,
                    deaths=village_mention.deaths,
                    injuries=village_mention.injuries,
                    evidence_span=village_mention.evidence_span,
                    matched_condition_id=condition.match.matched_id,
                    condition_confidence=condition.match.confidence,
                    condition_match_status=condition.match.status,
                    condition_review_required=condition.review_required,
                    raw_condition_text=self._condition_text_for_event(
                        extraction_result,
                        event_index,
                    ),
                    condition_review_reason=condition.review_reason,
                    condition_action_source=condition.action_source,
                    source_condition_text=condition.source_condition_text,
                    event_index=event_index,
                    event_location_count=event_size,
                    qualifier_text=village_mention.qualifier_text,
                    alias_matched=resolution.alias_hit,
                    resolved_by_geo_context=(geo_resolution.resolved_by_geo_context),
                    geo_context_anchor_village_id=(geo_resolution.anchor_village_id),
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
        location_ambiguity = bool(extraction_result.location_ambiguity)
        if location_ambiguity:
            village_matches = [
                vm.model_copy(
                    update={
                        "village_match_status": MatchResultStatus.matched_low_confidence,
                        "village_review_required": True,
                    }
                )
                for vm in village_matches
            ]
            any_village_low_confidence = True

        return MatchResultDTO(
            village_matches=village_matches,
            any_village_low_confidence=any_village_low_confidence,
            location_ambiguity=location_ambiguity,
            location_alternatives=list(extraction_result.location_alternatives),
            location_ambiguity_evidence=extraction_result.location_ambiguity_evidence,
            matched_condition_id=root_condition.match.matched_id,
            condition_confidence=root_condition.match.confidence,
            condition_match_status=root_condition.match.status,
            condition_review_required=root_condition.review_required,
            raw_condition_text=extraction_result.action_description,
            condition_review_reason=root_condition.review_reason,
            condition_action_source=root_condition.action_source,
            source_condition_text=root_condition.source_condition_text,
            sub_event_matches=sub_event_matches,
        )

    def _match_sub_event(
        self,
        index: int,
        sub_event,
        *,
        cnrs_classification: dict | None = None,
    ) -> SubEventMatchResult:
        condition = self._resolve_condition(
            sub_event.action_description,
            source_hint=None,
            action_source=None,
            cnrs_classification=cnrs_classification,
        )
        return SubEventMatchResult(
            index=index,
            action_description=sub_event.action_description,
            evidence_span=sub_event.evidence_span,
            matched_condition_id=condition.match.matched_id,
            condition_confidence=condition.match.confidence,
            condition_match_status=condition.match.status,
            condition_review_required=condition.review_required,
            condition_review_reason=condition.review_reason,
            condition_action_source=condition.action_source,
            source_condition_text=condition.source_condition_text,
        )

    @staticmethod
    def _condition_text_for_event(
        extraction_result: ExtractionResult,
        event_index: int | None,
    ) -> str | None:
        if event_index is None:
            return extraction_result.action_description
        if 0 <= event_index < len(extraction_result.sub_events):
            return extraction_result.sub_events[event_index].action_description
        return extraction_result.action_description

    @staticmethod
    def _event_village_mentions(
        extraction_result: ExtractionResult,
        sub_event_matches: list[SubEventMatchResult],
        root_condition: _ConditionResolution,
    ) -> list[tuple[VillageRoleEntry, int | None, int | None, _ConditionResolution]]:
        items: list[
            tuple[VillageRoleEntry, int | None, int | None, _ConditionResolution]
        ] = []
        for index, sub_event in enumerate(extraction_result.sub_events):
            if not sub_event.locations:
                continue
            match = sub_event_matches[index] if index < len(sub_event_matches) else None
            condition = (
                _ConditionResolution(
                    _ClassifiedMatch(
                        match.matched_condition_id,
                        match.condition_confidence,
                        match.condition_match_status,
                    ),
                    bool(match.condition_review_required),
                    match.condition_review_reason,
                    match.condition_action_source,
                    match.source_condition_text,
                )
                if match is not None
                else root_condition
            )
            if (
                condition.match.status == MatchResultStatus.unmatched
                and root_condition.match.status
                in {MatchResultStatus.matched, MatchResultStatus.matched_low_confidence}
            ):
                condition = root_condition
            event_size = len(sub_event.locations)
            for location in sub_event.locations:
                items.append((location, index, event_size, condition))
        if items:
            return items
        return [
            (mention, None, None, root_condition)
            for mention in MatchingService._village_mentions(extraction_result)
        ]

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

    @staticmethod
    def _context_anchor_mentions(
        extraction_result: ExtractionResult,
        event_mentions: list[
            tuple[VillageRoleEntry, int | None, int | None, _ClassifiedMatch]
        ],
    ) -> list[str]:
        event_names = {
            normalize_arabic_text(mention.village)
            for mention, _event_index, _event_size, _condition in event_mentions
        }
        candidates = [
            village
            for village in (extraction_result.village or [])
            if normalize_arabic_text(village) not in event_names
        ]
        candidates.extend(
            mention.qualifier_text
            for mention, _event_index, _event_size, _condition in event_mentions
            if mention.qualifier_text
            and not normalize_arabic_text(mention.qualifier_text).startswith(
                ("حي ", "محله ", "حاره ", "قضاء ", "منطقه ")
            )
        )
        return list(dict.fromkeys(candidates))

    def _resolve_village_candidates(
        self,
        mention: str | None,
        *,
        qualifier_text: str | None = None,
    ) -> _VillageCandidateResolution:
        normalized = normalize_arabic_text(mention or "")
        if not normalized:
            return _VillageCandidateResolution(
                (),
                _ClassifiedMatch(None, None, MatchResultStatus.unmatched),
            )
        district_hint = _district_hint(
            " ".join(part for part in (normalized, qualifier_text or "") if part)
        )
        search_text = _strip_district_hint(normalized)
        if _is_exception_match(search_text, _village_match_exceptions()):
            return _VillageCandidateResolution(
                (),
                _ClassifiedMatch(
                    None,
                    None,
                    MatchResultStatus.matched_low_confidence,
                ),
            )

        resolve_alias = getattr(self.villages, "resolve_alias", None)
        if resolve_alias is not None and district_hint is None:
            alias_hit = resolve_alias(search_text)
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

        lexical_candidates = tuple(
            (candidate, max(0.0, min(float(score), 1.0)))
            for candidate, score in self.villages.find_similar(
                search_text,
                self.candidate_limit,
            )
        )
        conditional_aliases = self._geo_conditional_alias_candidates(search_text)
        existing_candidate_ids = {
            candidate.id for candidate, _score in lexical_candidates
        }
        conditional_candidates = tuple(
            (candidate, score)
            for candidate, score in conditional_aliases
            if candidate.id not in existing_candidate_ids
        )
        candidates = lexical_candidates + conditional_candidates
        district_resolved = False
        if district_hint:
            district_candidates = tuple(
                (candidate, max(score, MATCH_THRESHOLD + 0.1))
                for candidate, score in lexical_candidates
                if self._candidate_matches_district(candidate, district_hint)
                and self._has_lexical_overlap(search_text, candidate)
            )
            if district_candidates:
                candidates = tuple(
                    sorted(district_candidates, key=lambda item: item[1], reverse=True)
                )
                lexical_candidates = candidates
                district_resolved = True
        classified = self._classify_candidates(lexical_candidates, search_text)
        no_reference_overlap = (
            not district_resolved
            and classified.status == MatchResultStatus.matched
            and bool(lexical_candidates)
            and not self._has_lexical_overlap(search_text, lexical_candidates[0][0])
        )
        if no_reference_overlap:
            classified = _ClassifiedMatch(
                classified.matched_id,
                classified.confidence,
                MatchResultStatus.matched_low_confidence,
            )
        collision_like = (
            False
            if district_resolved
            else (
                bool(conditional_aliases)
                or self._has_collision_like_alternative(search_text, candidates)
            )
        )
        if collision_like and classified.status == MatchResultStatus.matched:
            classified = _ClassifiedMatch(
                classified.matched_id,
                classified.confidence,
                MatchResultStatus.matched_low_confidence,
            )
        return _VillageCandidateResolution(
            candidates,
            classified,
            collision_like=collision_like,
            conditional_candidate_ids=frozenset(
                candidate.id for candidate, _score in conditional_candidates
            ),
        )

    def _geo_conditional_alias_candidates(
        self,
        normalized_mention: str,
    ) -> tuple[tuple[Village, float], ...]:
        find_aliases = getattr(self.villages, "find_geo_conditional_aliases", None)
        if find_aliases is None:
            return ()
        return tuple(
            (candidate, max(0.0, min(float(score), 1.0)))
            for candidate, score in find_aliases(normalized_mention)
        )

    @staticmethod
    def _has_lexical_overlap(
        normalized_mention: str,
        candidate: Village,
    ) -> bool:
        """Guard against a trigram-only match with no textual relationship.

        When the gazetteer has no real entry for a place name (e.g. no ACS
        row and no alias), pure similarity scoring can still clear
        MATCH_THRESHOLD against an unrelated village purely by n-gram
        coincidence (recon: "بيوت السياد" -> "المنصوري"). Require the mention
        to share at least one meaningful token, or a substring relationship,
        with one of the candidate's known name fields before trusting a
        "matched" verdict. Candidates with no comparable name data (test
        stubs, or a mention too short to tokenize) are left unaffected.
        """
        mention_normalized = normalize_arabic_text(normalized_mention)
        mention_compact = normalize_arabic_text(normalized_mention, compact=True)
        mention_tokens = [
            token for token in mention_normalized.split() if len(token) >= 3
        ]
        references = [
            normalize_arabic_text(value or "")
            for value in (
                getattr(candidate, "ref_name_ar", None),
                getattr(candidate, "acs_name", None),
                getattr(candidate, "cad_name", None),
            )
        ]
        references = [reference for reference in references if reference]
        if not mention_tokens or not references:
            return True
        for reference in references:
            reference_tokens = [
                token for token in reference.split() if len(token) >= 3
            ]
            if any(token in reference_tokens for token in mention_tokens):
                return True
            if any(
                token in reference or reference in token for token in mention_tokens
            ):
                return True
            # Compact-form comparison catches legitimate spacing variants
            # ("كفرشوبا" vs "كفر شوبا") that a whitespace-token split misses.
            reference_compact = reference.replace(" ", "")
            if mention_compact and (
                mention_compact == reference_compact
                or mention_compact in reference_compact
                or reference_compact in mention_compact
            ):
                return True
        return False

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
            reference_tokens = reference.split()
            mention_tokens = mention.split()
            contains_mention = (
                reference == mention
                or reference.startswith(f"{mention} ")
                or _contains_token_sequence(reference_tokens, mention_tokens)
            )
            if contains_mention:
                matching_candidates += 1
        return matching_candidates >= 2

    @staticmethod
    def _rank_by_district_hint(
        candidates: tuple[tuple[Village, float], ...],
        district_hint: str,
    ) -> tuple[tuple[Village, float], ...]:
        if not candidates:
            return candidates
        boosted: list[tuple[Village, float, bool]] = []
        hint = normalize_arabic_text(district_hint)
        for candidate, score in candidates:
            caza_ar = normalize_arabic_text(getattr(candidate, "caza_ar", None) or "")
            caza_en = normalize_arabic_text(getattr(candidate, "caza_en", None) or "")
            district_match = bool(hint and (hint in caza_ar or hint in caza_en))
            if hint and (hint in caza_ar or hint in caza_en):
                boosted.append(
                    (
                        candidate,
                        min(1.0, max(score, MATCH_THRESHOLD + 0.1)),
                        district_match,
                    )
                )
            else:
                boosted.append(
                    (candidate, min(score, LOW_CONFIDENCE_THRESHOLD), district_match)
                )
        ranked = sorted(boosted, key=lambda item: (item[2], item[1]), reverse=True)
        return tuple((candidate, score) for candidate, score, _matched in ranked)

    @staticmethod
    def _candidate_matches_district(candidate: Village, district_hint: str) -> bool:
        hint = normalize_arabic_text(district_hint)
        if not hint:
            return False
        for value in (
            getattr(candidate, "caza_ar", None),
            getattr(candidate, "caza_en", None),
        ):
            district = normalize_arabic_text(value or "")
            if district and (hint == district or hint in district or district in hint):
                return True
        return False

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
            and (
                not resolution.conditional_candidate_ids
                or candidate.id == resolution.candidates[0][0].id
                or candidate.id in resolution.conditional_candidate_ids
            )
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
            resolution.classified.status != MatchResultStatus.matched_low_confidence
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

    def _resolve_condition(
        self,
        text: str | None,
        *,
        source_hint: str | None,
        action_source: str | None,
        cnrs_classification: dict | None = None,
    ) -> _ConditionResolution:
        text_match = self._match_mention(
            text,
            self.conditions.find_similar,
            guard_condition_tokens=True,
            cnrs_classification=cnrs_classification,
        )
        source_match = self._match_mention(
            source_hint,
            self.conditions.find_similar,
            guard_condition_tokens=True,
            cnrs_classification=cnrs_classification,
        )
        source_available = source_match.matched_id is not None

        if (
            text_match.status == MatchResultStatus.matched
            and source_available
            and source_match.matched_id != text_match.matched_id
        ):
            return _ConditionResolution(
                text_match,
                True,
                (
                    "Condition text evidence disagrees with source metadata "
                    f"(text: {text or 'unclassified'}, source: {source_hint})."
                ),
                "llm_text",
                source_hint,
            )

        if text_match.status == MatchResultStatus.matched:
            return _ConditionResolution(
                text_match,
                False,
                None,
                action_source or "llm_text",
                source_hint,
            )

        if (
            source_available
            and source_match.matched_id in EFFECT_DEFINED_CONDITION_IDS
            and text
            and not self._condition_match_allowed(
                source_match.matched_id,
                normalize_arabic_text(text),
                cnrs_classification=cnrs_classification,
            )
        ):
            source_available = False

        if source_available:
            confidence = min(float(source_match.confidence or 0.0), MATCH_THRESHOLD - 0.01)
            return _ConditionResolution(
                _ClassifiedMatch(
                    source_match.matched_id,
                    confidence,
                    MatchResultStatus.matched_low_confidence,
                ),
                True,
                (
                    "Source metadata fallback used because no confident "
                    f"text-grounded condition was available (source: {source_hint})."
                ),
                "cnrs_subtype_fallback",
                source_hint,
            )

        if text_match.status == MatchResultStatus.matched_low_confidence:
            return _ConditionResolution(
                text_match,
                True,
                f"Low-confidence condition text match requires review (text: {text}).",
                "llm_text",
                source_hint,
            )

        unclassified = self._match_unclassified_condition()
        if unclassified.matched_id is not None:
            unclassified = _ClassifiedMatch(
                unclassified.matched_id,
                min(float(unclassified.confidence or 0.0), MATCH_THRESHOLD - 0.01),
                MatchResultStatus.matched_low_confidence,
            )
        return _ConditionResolution(
            unclassified,
            True,
            "No usable text-grounded or source-metadata condition candidate.",
            "unclassified",
            source_hint,
        )

    def _match_unclassified_condition(self) -> _ClassifiedMatch:
        label = "Unclassified / Needs Review"
        candidates = tuple(
            (candidate, max(0.0, min(float(score), 1.0)))
            for candidate, score in self.conditions.find_similar(
                label,
                self.candidate_limit,
            )
            if getattr(candidate, "action_en", None) == label
            or getattr(candidate, "action_ar", None) == "غير مصنف / بحاجة إلى مراجعة"
        )
        return self._classify_candidates(candidates, label)

    def _match_mention(
        self,
        mention: str | None,
        find_similar: Callable[
            [str, int],
            list[tuple[Village, float]] | list[tuple[Condition, float]],
        ],
        *,
        allow_alias: bool = False,
        guard_condition_tokens: bool = False,
        cnrs_classification: dict | None = None,
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
        return self._classify_candidates(
            candidates,
            normalized,
            guard_condition_tokens=guard_condition_tokens,
            cnrs_classification=cnrs_classification,
        )

    def _classify_candidates(
        self,
        candidates: tuple[
            tuple[Village | Condition, float],
            ...,
        ],
        normalized: str,
        *,
        guard_condition_tokens: bool = False,
        cnrs_classification: dict | None = None,
    ) -> _ClassifiedMatch:
        if not candidates:
            return _ClassifiedMatch(None, None, MatchResultStatus.unmatched)
        allowed: list[tuple[Village | Condition, float]] = []
        for candidate, score in candidates:
            if guard_condition_tokens and not self._condition_match_allowed(
                candidate.id,
                normalized,
                cnrs_classification=cnrs_classification,
            ):
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
    def _condition_match_allowed(
        condition_id: int,
        normalized_text: str,
        *,
        cnrs_classification: dict | None = None,
    ) -> bool:
        if _is_exception_match(normalized_text, _condition_match_exceptions()):
            return False
        required_tokens = CONDITION_DISTINGUISHING_TOKENS.get(condition_id)
        if required_tokens is None:
            if condition_id not in EFFECT_DEFINED_CONDITION_IDS:
                return True
            if normalized_text.lower() == EFFECT_DEFINED_CANONICAL_ACTIONS.get(condition_id):
                return True
            return has_conflict_attribution_text(
                normalized_text
            ) or MatchingService._cnrs_conflict_attribution(cnrs_classification)
        return any(token in normalized_text for token in required_tokens)

    @staticmethod
    def _cnrs_conflict_attribution(classification: dict | None) -> bool:
        if not classification or classification.get("include") is not True:
            return False
        if classification.get("mentions_israeli_actor") is True:
            return True
        domain = str(classification.get("event_domain") or "").strip().lower()
        subtype = str(classification.get("event_subtype") or "").strip().lower()
        return domain == "conflict" or subtype in {
            "airstrike",
            "artillery",
            "direct_attack",
        }
