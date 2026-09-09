from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.llm.dtos import ExtractionResult, VillageRole, VillageRoleEntry
from app.news.actions.match_incident_action import MatchIncidentAction
from app.news.dtos import (
    MatchResultDTO,
    MatchResultStatus,
)
from app.news.dtos.match_result_dto import VillageMatchResult
from app.news.services.matching.matching_service import MatchingService


class _SimilarRepositoryStub:
    def __init__(self, candidate_id: int | None, score: float | None) -> None:
        self.candidate_id = candidate_id
        self.score = score
        self.calls: list[tuple[str, int]] = []

    def find_similar(self, text: str, limit: int = 5):
        self.calls.append((text, limit))
        if self.candidate_id is None or self.score is None:
            return []
        return [(SimpleNamespace(id=self.candidate_id), self.score)]


class _MultiSimilarRepositoryStub:
    """Returns a fixed candidate list (for tie-margin regressions)."""

    def __init__(self, candidates: list[tuple[int, float]]) -> None:
        self.candidates = candidates
        self.calls: list[tuple[str, int]] = []

    def find_similar(self, text: str, limit: int = 5):
        self.calls.append((text, limit))
        return [
            (SimpleNamespace(id=candidate_id), score)
            for candidate_id, score in self.candidates[:limit]
        ]


def _extraction(
    village: list[str] | None = None,
    action: str | None = "غارة جوية",
    village_roles: list[VillageRoleEntry] | None = None,
) -> ExtractionResult:
    if village is None:
        village = ["أيتا الشعب"]
    return ExtractionResult(
        is_relevant=True,
        village=village,
        village_roles=village_roles or [],
        action_description=action,
        model="test",
        extracted_at=datetime.now(timezone.utc),
    )


@pytest.mark.parametrize(
    ("score", "expected_id", "status", "review_required"),
    [
        (0.6, 11, MatchResultStatus.matched, False),
        (0.35, 11, MatchResultStatus.matched_low_confidence, True),
        (0.349, None, MatchResultStatus.unmatched, True),
    ],
)
def test_classifies_village_thresholds(
    score: float,
    expected_id: int | None,
    status: MatchResultStatus,
    review_required: bool,
) -> None:
    villages = _SimilarRepositoryStub(11, score)
    conditions = _SimilarRepositoryStub(None, None)
    service = MatchingService(villages, conditions)

    result = service.match(_extraction(action=None))

    assert len(result.village_matches) == 1
    vm = result.village_matches[0]
    assert vm.matched_village_id == expected_id
    assert vm.village_confidence == score
    assert vm.village_match_status == status
    assert vm.village_review_required is review_required
    assert vm.village_role == VillageRole.target
    assert villages.calls == [("ايتا الشعب", 5)]


def test_matches_condition_and_preserves_raw_mentions() -> None:
    villages = _SimilarRepositoryStub(None, None)
    conditions = _SimilarRepositoryStub(22, 0.81)
    service = MatchingService(villages, conditions)
    extraction = _extraction(village=[], action="غارة جوية")

    result = service.match(extraction)

    assert result.matched_condition_id == 22
    assert result.condition_match_status == MatchResultStatus.matched
    assert result.condition_review_required is False
    assert result.village_matches == []
    assert result.raw_condition_text == "غارة جوية"
    assert villages.calls == []


def test_multi_village_produces_two_match_entries() -> None:
    villages = _SimilarRepositoryStub(11, 0.75)
    conditions = _SimilarRepositoryStub(None, None)
    service = MatchingService(villages, conditions)

    result = service.match(
        _extraction(
            village=["كفرتبنيت", "حرش عيتا الجبل"],
            action=None,
        )
    )

    assert len(result.village_matches) == 2
    assert result.village_matches[0].raw_village_text == "كفرتبنيت"
    assert result.village_matches[1].raw_village_text == "حرش عيتا الجبل"
    assert result.village_matches[0].matched_village_id == 11
    assert result.village_matches[1].matched_village_id == 11
    assert all(item.village_role == VillageRole.target for item in result.village_matches)


def test_village_roles_are_preserved_in_match_entries() -> None:
    villages = _SimilarRepositoryStub(11, 0.75)
    conditions = _SimilarRepositoryStub(None, None)
    service = MatchingService(villages, conditions)

    result = service.match(
        _extraction(
            village=["البياض", "المنصوري"],
            action=None,
            village_roles=[
                VillageRoleEntry(village="البياض", role=VillageRole.origin),
                VillageRoleEntry(
                    village="المنصوري",
                    role=VillageRole.target,
                    deaths=1,
                    injuries=3,
                    evidence_span="المنصوري: شهيد و3 جرحى",
                ),
            ],
        )
    )

    assert [item.village_role for item in result.village_matches] == [
        VillageRole.origin,
        VillageRole.target,
    ]
    assert [item.raw_village_text for item in result.village_matches] == [
        "البياض",
        "المنصوري",
    ]
    assert result.village_matches[1].deaths == 1
    assert result.village_matches[1].injuries == 3
    assert (
        result.village_matches[1].evidence_span
        == "المنصوري: شهيد و3 جرحى"
    )


def test_any_village_low_confidence_flag_set_correctly() -> None:
    villages_lc = _SimilarRepositoryStub(11, 0.40)
    conditions = _SimilarRepositoryStub(None, None)
    service = MatchingService(villages_lc, conditions)

    result = service.match(_extraction(village=["بنت جبيل"], action=None))

    assert result.any_village_low_confidence is True

    villages_full = _SimilarRepositoryStub(11, 0.85)
    service2 = MatchingService(villages_full, conditions)
    result2 = service2.match(_extraction(village=["بنت جبيل"], action=None))
    assert result2.any_village_low_confidence is False


def test_generic_strike_does_not_match_warning_or_feigned_without_distinguishing_words() -> None:
    villages = _SimilarRepositoryStub(None, None)
    warning_conditions = _SimilarRepositoryStub(2, 0.4615)
    service = MatchingService(villages, warning_conditions)

    result = service.match(
        _extraction(village=None, action="غارة تستهدف بلدة المنصوري")
    )

    assert result.matched_condition_id is None
    assert result.condition_match_status == MatchResultStatus.unmatched


def test_warning_raid_still_matches_when_distinguishing_word_present() -> None:
    villages = _SimilarRepositoryStub(None, None)
    conditions = _SimilarRepositoryStub(2, 1.0)
    service = MatchingService(villages, conditions)

    result = service.match(
        _extraction(
            village=None,
            action="غارة تحذيرية من مسيرة على البيسارية",
        )
    )

    assert result.matched_condition_id == 2
    assert result.condition_match_status == MatchResultStatus.matched


def test_feigned_attacks_still_matches_when_distinguishing_word_present() -> None:
    villages = _SimilarRepositoryStub(None, None)
    conditions = _SimilarRepositoryStub(39, 1.0)
    service = MatchingService(villages, conditions)

    result = service.match(
        _extraction(
            village=None,
            action="طيران العدو الحربي ينفذ غارات وهمية",
        )
    )

    assert result.matched_condition_id == 39
    assert result.condition_match_status == MatchResultStatus.matched


def test_verbose_airstrike_uses_word_similarity_score_without_matching_artillery() -> None:
    verbose_airstrike = (
        "الطيران الحربي الإسرائيلي أغار مستهدفًا بلدة المنصوري بغارتين"
    )
    villages = _SimilarRepositoryStub(None, None)
    airstrike_conditions = _SimilarRepositoryStub(35, 0.466667)
    service = MatchingService(villages, airstrike_conditions)

    result = service.match(
        _extraction(village=None, action=verbose_airstrike)
    )

    assert result.matched_condition_id == 35
    assert result.condition_match_status == MatchResultStatus.matched_low_confidence
    assert result.condition_confidence == 0.466667

    artillery_conditions = _SimilarRepositoryStub(5, 0.1)
    unrelated_result = MatchingService(
        villages,
        artillery_conditions,
    ).match(_extraction(village=None, action=verbose_airstrike))

    assert unrelated_result.matched_condition_id is None
    assert unrelated_result.condition_match_status == MatchResultStatus.unmatched


class _MatchingServiceStub:
    def __init__(self, result: MatchResultDTO) -> None:
        self.result = result
        self.received: ExtractionResult | None = None

    def match(self, extraction_result: ExtractionResult) -> MatchResultDTO:
        self.received = extraction_result
        return self.result


class _RawMessageRepositoryStub:
    def __init__(self, message) -> None:
        self.message = message
        self.saved: tuple[object, MatchResultDTO] | None = None

    def get_parsed_by_id(self, raw_message_id: int):
        return self.message if self.message.id == raw_message_id else None

    def save_match_result(self, message, result: MatchResultDTO) -> None:
        self.saved = (message, result)


def test_action_reads_extraction_and_persists_match_result() -> None:
    expected = MatchResultDTO(
        village_matches=[
            VillageMatchResult(
                matched_village_id=11,
                village_confidence=0.7,
                village_match_status=MatchResultStatus.matched,
                village_review_required=False,
                raw_village_text="بنت جبيل",
            )
        ],
        any_village_low_confidence=False,
        matched_condition_id=None,
        condition_confidence=0.2,
        condition_match_status=MatchResultStatus.unmatched,
        condition_review_required=True,
        raw_condition_text="حدث غير معروف",
    )
    message = SimpleNamespace(
        id=42,
        extraction_result=_extraction(
            village=["بنت جبيل"],
            action="حدث غير معروف",
        ).model_dump(mode="json"),
    )
    repository = _RawMessageRepositoryStub(message)
    service = _MatchingServiceStub(expected)

    result = MatchIncidentAction(repository, service).execute(42)

    assert result == expected
    assert service.received is not None
    assert service.received.village == ["بنت جبيل"]
    assert repository.saved == (message, expected)


def test_action_rejects_message_without_extraction_result() -> None:
    repository = _RawMessageRepositoryStub(
        SimpleNamespace(id=42, extraction_result=None)
    )
    service = _MatchingServiceStub(None)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="has no extraction_result"):
        MatchIncidentAction(repository, service).execute(42)


def test_action_does_not_persist_match_when_air_violation_routing_fails() -> None:
    expected = MatchResultDTO(
        village_matches=[],
        any_village_low_confidence=False,
        matched_condition_id=36,
        condition_confidence=1.0,
        condition_match_status=MatchResultStatus.matched,
        condition_review_required=False,
        raw_condition_text="surveillance aircraft",
    )
    message = SimpleNamespace(
        id=42,
        extraction_result=_extraction(
            village=None,
            action="surveillance aircraft",
        ).model_dump(mode="json"),
    )
    repository = _RawMessageRepositoryStub(message)

    class _FailingAirViolationRepository:
        def route_from_match(self, routed_message, result) -> None:
            raise RuntimeError("routing failed")

    with pytest.raises(RuntimeError, match="routing failed"):
        MatchIncidentAction(
            repository,
            _MatchingServiceStub(expected),
            _FailingAirViolationRepository(),  # type: ignore[arg-type]
        ).execute(42)

    assert repository.saved is None


def test_nabatiyeh_style_near_tie_downgrades_to_low_confidence() -> None:
    """Recon: five * النبطية villages tied at ~0.615; lowest id must not auto-match."""
    villages = _MultiSimilarRepositoryStub(
        [
            (543, 0.615385),  # Douair — would have won by id ASC alone
            (614, 0.615385),
            (741, 0.615385),
            (874, 0.615385),
            (1366, 0.615385),
        ]
    )
    service = MatchingService(villages, _SimilarRepositoryStub(None, None))

    result = service.match(_extraction(village=["النبطية"], action=None))

    vm = result.village_matches[0]
    assert vm.matched_village_id == 543
    assert vm.village_confidence == pytest.approx(0.615385)
    assert vm.village_match_status == MatchResultStatus.matched_low_confidence
    assert vm.village_review_required is True
    assert result.any_village_low_confidence is True


def test_clear_winner_above_margin_stays_confident_match() -> None:
    villages = _MultiSimilarRepositoryStub(
        [
            (1153, 0.733333),  # النبطية الفوقا style
            (543, 0.444444),
            (614, 0.444444),
        ]
    )
    service = MatchingService(villages, _SimilarRepositoryStub(None, None))

    result = service.match(_extraction(village=["النبطية الفوقا"], action=None))

    vm = result.village_matches[0]
    assert vm.matched_village_id == 1153
    assert vm.village_match_status == MatchResultStatus.matched
    assert vm.village_review_required is False


def test_near_tie_within_margin_downgrades_even_when_top_exceeds_threshold() -> None:
    villages = _MultiSimilarRepositoryStub(
        [
            (100, 0.62),
            (200, 0.60),  # margin 0.02 < 0.05
        ]
    )
    service = MatchingService(villages, _SimilarRepositoryStub(None, None))

    result = service.match(_extraction(village=["قرية"], action=None))

    assert result.village_matches[0].village_match_status == (
        MatchResultStatus.matched_low_confidence
    )


class _GeoVillageRepositoryStub:
    def __init__(
        self,
        candidates_by_text,
        aliases=None,
    ) -> None:
        self.candidates_by_text = candidates_by_text
        self.aliases = aliases or {}

    def resolve_alias(self, normalized_text: str):
        village = self.aliases.get(normalized_text)
        return (village, 1.0) if village is not None else None

    def find_similar(self, text: str, limit: int = 5):
        return self.candidates_by_text.get(text, [])[:limit]


def _geo_village(
    village_id: int,
    ref_name_ar: str,
    coord_x: float,
    coord_y: float,
):
    return SimpleNamespace(
        id=village_id,
        ref_name_ar=ref_name_ar,
        coord_x=coord_x,
        coord_y=coord_y,
    )


def test_geo_context_resolves_zibdine_near_harouf() -> None:
    harouf = _geo_village(652, "حروف", 727118.662568, 3695226.05415)
    zibdine_jbayl = _geo_village(
        1530,
        "زبدين",
        749917.749312,
        3776011.05529,
    )
    bzebdine = _geo_village(
        395,
        "بزبدين",
        753227.718606,
        3751453.96821,
    )
    zibdine_nabatiyeh = _geo_village(
        1529,
        "زبدين النبطية",
        729089.964486,
        3695394.05526,
    )
    villages = _GeoVillageRepositoryStub(
        {
            "زبدين": [
                (zibdine_jbayl, 1.0),
                (bzebdine, 0.44444445),
                (zibdine_nabatiyeh, 0.42857143),
            ]
        },
        aliases={"حاروف": harouf},
    )
    service = MatchingService(villages, _SimilarRepositoryStub(None, None))

    result = service.match(
        _extraction(village=["حاروف", "زبدين"], action=None)
    )

    assert result.village_matches[0].matched_village_id == harouf.id
    zibdine_match = result.village_matches[1]
    assert zibdine_match.matched_village_id == zibdine_nabatiyeh.id
    assert zibdine_match.village_match_status == MatchResultStatus.matched
    assert zibdine_match.resolved_by_geo_context is True
    assert zibdine_match.geo_context_anchor_village_id == harouf.id
    assert zibdine_match.original_top_candidate_id == zibdine_jbayl.id
    assert (
        zibdine_match.alternate_candidate_village_id
        == zibdine_jbayl.id
    )


def test_exact_duplicate_without_anchor_keeps_low_confidence_winner() -> None:
    first = _geo_village(100, "كنيسة", 0, 0)
    second = _geo_village(200, "كنيسة", 100000, 100000)
    villages = _GeoVillageRepositoryStub(
        {"كنيسه": [(first, 1.0), (second, 1.0)]}
    )
    service = MatchingService(villages, _SimilarRepositoryStub(None, None))

    result = service.match(_extraction(village=["كنيسة"], action=None))

    village_match = result.village_matches[0]
    assert village_match.matched_village_id == first.id
    assert (
        village_match.village_match_status
        == MatchResultStatus.matched_low_confidence
    )
    assert village_match.resolved_by_geo_context is False
    assert village_match.alternate_candidate_village_id == second.id


def test_region_suffixed_collision_without_anchor_is_reviewable() -> None:
    plain = _geo_village(100, "زبدين", 80000, 0)
    lexical_runner_up = _geo_village(200, "بزبدين", 40000, 0)
    region_qualified = _geo_village(300, "زبدين النبطية", 0, 0)
    villages = _GeoVillageRepositoryStub(
        {
            "زبدين": [
                (plain, 1.0),
                (lexical_runner_up, 0.44),
                (region_qualified, 0.42),
            ]
        }
    )
    service = MatchingService(villages, _SimilarRepositoryStub(None, None))

    result = service.match(_extraction(village=["زبدين"], action=None))

    village_match = result.village_matches[0]
    assert village_match.matched_village_id == plain.id
    assert (
        village_match.village_match_status
        == MatchResultStatus.matched_low_confidence
    )
    assert village_match.village_review_required is True
    assert village_match.alternate_candidate_village_id == region_qualified.id


def test_geo_context_requires_meaningful_distance_advantage() -> None:
    anchor = _geo_village(10, "مرساة", 0, 0)
    original = _geo_village(20, "قرية", 10000, 0)
    slightly_closer = _geo_village(30, "قرية", 9000, 0)
    villages = _GeoVillageRepositoryStub(
        {"قريه": [(original, 1.0), (slightly_closer, 1.0)]},
        aliases={"مرساة": anchor},
    )
    service = MatchingService(
        villages,
        _SimilarRepositoryStub(None, None),
        geo_context_max_distance_meters=20000,
        geo_context_min_distance_advantage_meters=5000,
    )

    result = service.match(
        _extraction(village=["مرساة", "قرية"], action=None)
    )

    village_match = result.village_matches[1]
    assert village_match.matched_village_id == original.id
    assert (
        village_match.village_match_status
        == MatchResultStatus.matched_low_confidence
    )
    assert village_match.resolved_by_geo_context is False
