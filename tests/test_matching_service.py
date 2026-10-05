from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.core.text_normalization import normalize_arabic_text
from app.llm.dtos import (
    ExtractionCasualties,
    ExtractionResult,
    ExtractionSubEvent,
    VillageRole,
    VillageRoleEntry,
)
from app.news.actions.match_incident_action import MatchIncidentAction
from app.news.dtos import (
    MatchResultDTO,
    MatchResultStatus,
)
from app.news.dtos.match_result_dto import VillageMatchResult
from app.news.models import MessageStatus
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


class _TextSimilarRepositoryStub:
    def __init__(self, candidates_by_text) -> None:
        self.candidates_by_text = candidates_by_text
        self.calls: list[tuple[str, int]] = []

    def find_similar(self, text: str, limit: int = 5):
        self.calls.append((text, limit))
        return self.candidates_by_text.get(text, [])[:limit]


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


def test_wadi_phrase_does_not_confidently_fuzzy_match_unrelated_ouadi_village() -> None:
    village = SimpleNamespace(
        id=1200,
        ref_name_ar="وادي الدير",
        acs_name=None,
        cad_name=None,
    )
    villages = _TextSimilarRepositoryStub({"وادي الحجير": [(village, 0.91)]})
    conditions = _SimilarRepositoryStub(None, None)
    service = MatchingService(villages, conditions)

    result = service.match(_extraction(village=["وادي الحجير"], action=None))

    vm = result.village_matches[0]
    assert vm.matched_village_id == 1200
    assert vm.village_match_status == MatchResultStatus.matched_low_confidence
    assert vm.village_review_required is True


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
    assert all(
        item.village_role == VillageRole.target for item in result.village_matches
    )


def test_fuzzy_area_village_is_one_low_confidence_match() -> None:
    villages = _SimilarRepositoryStub(969, 1.0)
    conditions = _SimilarRepositoryStub(None, None)
    extraction = _extraction(
        village=["مجدل زون"],
        action="إحراق حقول في محيط مجدل زون وبيوت السياد",
        village_roles=[VillageRoleEntry(village="مجدل زون")],
    ).model_copy(
        update={
            "location_ambiguity": True,
            "location_alternatives": ["بيوت السياد"],
            "location_ambiguity_evidence": "محيط مجدل زون وبيوت السياد",
        }
    )

    result = MatchingService(villages, conditions).match(extraction)

    assert len(result.village_matches) == 1
    assert result.village_matches[0].raw_village_text == "مجدل زون"
    assert result.village_matches[0].village_match_status == (
        MatchResultStatus.matched_low_confidence
    )
    assert result.village_matches[0].village_review_required is True
    assert result.any_village_low_confidence is True
    assert result.location_alternatives == ["بيوت السياد"]


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
    assert result.village_matches[1].evidence_span == "المنصوري: شهيد و3 جرحى"


def test_message_10387_parenthetical_qualifier_is_not_a_second_village() -> None:
    extraction = _extraction(
        village=["فرون", "وادي الخنازير"],
        action=None,
        village_roles=[
            VillageRoleEntry(
                village="فرون",
                qualifier_text="وادي الخنازير",
            )
        ],
    )

    result = MatchingService(
        _SimilarRepositoryStub(10387, 0.9),
        _SimilarRepositoryStub(None, None),
    ).match(extraction)

    assert len(result.village_matches) == 1
    assert result.village_matches[0].raw_village_text == "فرون"
    assert result.village_matches[0].qualifier_text == "وادي الخنازير"


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


def test_ungazetteered_place_does_not_silently_match_unrelated_village() -> None:
    """Recon: "بيوت السياد" has no ACS row and no alias; pure trigram
    similarity landed on "المنصوري" (an unrelated South Lebanon village)
    with a clear score margin, so the old tie-margin-only check let it
    through as a confident match. There must be no lexical relationship
    between the two names, so this should downgrade instead of matching.
    """
    mansouri = SimpleNamespace(
        id=42,
        ref_name_ar="المنصوري",
        acs_name=None,
        cad_name=None,
        caza_ar=None,
        caza_en=None,
    )
    villages = _GeoVillageRepositoryStub({"بيوت السياد": [(mansouri, 0.62)]})
    conditions = _SimilarRepositoryStub(None, None)
    service = MatchingService(villages, conditions)

    result = service.match(_extraction(village=["بيوت السياد"], action=None))

    vm = result.village_matches[0]
    assert vm.village_match_status == MatchResultStatus.matched_low_confidence
    assert vm.village_review_required is True


def test_confirmed_bouyout_sayyad_alias_overrides_similarity() -> None:
    mansouri = SimpleNamespace(
        id=42,
        ref_name_ar="المنصوري",
        acs_name=None,
        cad_name=None,
        caza_ar=None,
        caza_en=None,
    )
    villages = _GeoVillageRepositoryStub(
        {"بيوت السياد": [(mansouri, 0.99)]},
        aliases={"بيوت السياد": mansouri},
    )

    result = MatchingService(villages, _SimilarRepositoryStub(None, None)).match(
        _extraction(village=["بيوت السياد"], action=None)
    )

    vm = result.village_matches[0]
    assert vm.matched_village_id == 42
    assert vm.village_match_status == MatchResultStatus.matched
    assert vm.village_review_required is False
    assert vm.alias_matched is True


def test_wadi_selouqi_alias_overrides_baalbek_slouqi_similarity() -> None:
    touline = SimpleNamespace(
        id=1464,
        ref_name_ar="تولين",
        acs_name="Touline",
        cad_name="Touline",
        caza_ar="مرجعيون",
        caza_en="Marjaayoun",
    )
    slouqi = SimpleNamespace(
        id=1397,
        ref_name_ar="سلوقي",
        acs_name="Slouqi",
        cad_name="Slouky",
        caza_ar="بعلبك",
        caza_en="Baalbek",
    )
    villages = _GeoVillageRepositoryStub(
        {"وادي السلوقي": [(slouqi, 0.92)]},
        aliases={"وادي السلوقي": touline},
    )

    result = MatchingService(villages, _SimilarRepositoryStub(None, None)).match(
        _extraction(village=["وادي السلوقي"], action=None)
    )

    vm = result.village_matches[0]
    assert vm.matched_village_id == 1464
    assert vm.village_confidence == 1.0
    assert vm.village_match_status == MatchResultStatus.matched
    assert vm.village_review_required is False
    assert vm.alias_matched is True


@pytest.mark.parametrize(
    ("raw_name", "expected_id"),
    [
        ("وادي راج", 71367),
        ("الدبشة", 71133),
        ("جبل الرفيع", 71133),
        ("دبل", 72281),
        ("الجبين", 62292),
    ],
)
def test_confirmed_no_acs_aliases_override_similarity(raw_name: str, expected_id: int) -> None:
    target = SimpleNamespace(
        id=expected_id,
        ref_name_ar=raw_name,
        acs_name=None,
        cad_name=None,
        caza_ar=None,
        caza_en=None,
    )
    wrong = SimpleNamespace(
        id=999,
        ref_name_ar="الشرفية",
        acs_name=None,
        cad_name=None,
        caza_ar=None,
        caza_en=None,
    )
    villages = _GeoVillageRepositoryStub(
        {raw_name: [(wrong, 0.92)]},
        aliases={normalize_arabic_text(raw_name): target},
    )

    result = MatchingService(villages, _SimilarRepositoryStub(None, None)).match(
        _extraction(village=[raw_name], action=None)
    )

    vm = result.village_matches[0]
    assert vm.raw_village_text == raw_name
    assert vm.matched_village_id == expected_id
    assert vm.village_match_status == MatchResultStatus.matched
    assert vm.alias_matched is True


def test_qada_hint_does_not_force_unrelated_candidate_without_name_overlap() -> None:
    abbasiyeh = _geo_village(9001, "العباسية", 0, 0, caza_ar="صور")
    villages = _GeoVillageRepositoryStub(
        {
            "تل النحاس": [(abbasiyeh, 0.4)],
        }
    )

    result = MatchingService(villages, _SimilarRepositoryStub(None, None)).match(
        _extraction(village=["تل النحاس قضاء صور"], action=None)
    )

    vm = result.village_matches[0]
    assert vm.matched_village_id == abbasiyeh.id
    assert vm.village_match_status == MatchResultStatus.matched_low_confidence
    assert vm.village_review_required is True


def test_generic_strike_does_not_match_warning_or_feigned_without_distinguishing_words() -> (
    None
):
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


@pytest.mark.parametrize(
    ("condition_id", "negative_action", "positive_action"),
    [
        (
            17,
            "إطلاق نار خلال إشكال فردي في أحد الأحياء",
            "إطلاق نار معاد من موقع للعدو الإسرائيلي باتجاه البلدة",
        ),
        (
            21,
            "النيران تلتهم سيارة في العباسية... حريق كبير شرق صور",
            "تفجير عبوة ناسفة زرعتها قوات العدو الإسرائيلي خلال توغل بري",
        ),
        (
            24,
            "قطع طريق بسبب حادث سير وزحمة خانقة",
            "قطع طريق بعد قصف مدفعي إسرائيلي استهدف الطريق العام",
        ),
        (
            25,
            "حفر وجرف ضمن أشغال بلدية لتأهيل الطريق",
            "حفر وجرف نفذته جرافات العدو الإسرائيلي قرب الحدود",
        ),
        (
            26,
            "قطع أشجار ضمن أعمال تنظيف زراعية",
            "قطع أشجار نفذته قوات العدو خلال توغل بري",
        ),
        (
            27,
            "حريق داخل منزل في البحصة - طرابلس",
            "اندلاع حريق في منزل إثر قصف مدفعي إسرائيلي",
        ),
        (
            40,
            "العثور على جسم مشبوه غير منفجر قرب مكب نفايات",
            "العثور على قذائف لم تنفجر من مخلفات قصف إسرائيلي",
        ),
    ],
)
def test_effect_defined_conditions_require_conflict_attribution(
    condition_id: int,
    negative_action: str,
    positive_action: str,
) -> None:
    villages = _SimilarRepositoryStub(None, None)
    conditions = _SimilarRepositoryStub(condition_id, 1.0)
    service = MatchingService(villages, conditions)

    negative = service.match(_extraction(village=[], action=negative_action))

    assert negative.matched_condition_id is None
    assert negative.condition_match_status == MatchResultStatus.unmatched

    positive = service.match(_extraction(village=[], action=positive_action))

    assert positive.matched_condition_id == condition_id
    assert positive.condition_match_status == MatchResultStatus.matched


def test_cnrs_conflict_classification_allows_effect_defined_condition() -> None:
    villages = _SimilarRepositoryStub(None, None)
    conditions = _SimilarRepositoryStub(27, 1.0)
    service = MatchingService(villages, conditions)

    result = service.match(
        _extraction(village=[], action="حريق كبير"),
        cnrs_classification={
            "include": True,
            "event_domain": "conflict",
            "event_subtype": "airstrike",
        },
    )

    assert result.matched_condition_id == 27
    assert result.condition_match_status == MatchResultStatus.matched


def test_cnrs_ordinary_fire_classification_does_not_allow_effect_defined_condition() -> None:
    villages = _SimilarRepositoryStub(None, None)
    conditions = _SimilarRepositoryStub(27, 1.0)
    service = MatchingService(villages, conditions)

    result = service.match(
        _extraction(village=[], action="حريق كبير"),
        cnrs_classification={
            "include": True,
            "event_domain": "fire",
            "event_subtype": "fire_incident",
            "mentions_israeli_actor": False,
        },
    )

    assert result.matched_condition_id is None
    assert result.condition_match_status == MatchResultStatus.unmatched


def test_source_hint_cannot_restore_unattributed_effect_defined_condition() -> None:
    villages = _SimilarRepositoryStub(None, None)
    conditions = _SimilarRepositoryStub(21, 1.0)
    service = MatchingService(villages, conditions)

    extraction = _extraction(
        village=["Aabbassiyet Sour"],
        action="النيران تلتهم سيارة في العباسية... حريق كبير شرق صور",
    ).model_copy(update={"source_action_hint": "Mining & Detonation"})

    result = service.match(extraction)

    assert result.matched_condition_id is None
    assert result.condition_match_status == MatchResultStatus.unmatched
    assert result.condition_action_source == "unclassified"


def test_effect_defined_canonical_cnrs_override_can_still_match() -> None:
    result = MatchingService(
        _SimilarRepositoryStub(None, None),
        _SimilarRepositoryStub(27, 1.0),
    ).match(_extraction(village=[], action="Burning Properties"))

    assert result.matched_condition_id == 27
    assert result.condition_match_status == MatchResultStatus.matched


def test_condition_exception_blocks_even_with_conflict_attribution() -> None:
    result = MatchingService(
        _SimilarRepositoryStub(None, None),
        _SimilarRepositoryStub(21, 1.0),
    ).match(
        _extraction(
            village=[],
            action="النيران تلتهم سيارة في العباسية بعد قصف",
        )
    )

    assert result.matched_condition_id is None
    assert result.condition_match_status == MatchResultStatus.unmatched


def test_verbose_airstrike_uses_word_similarity_score_without_matching_artillery() -> (
    None
):
    verbose_airstrike = "الطيران الحربي الإسرائيلي أغار مستهدفًا بلدة المنصوري بغارتين"
    villages = _SimilarRepositoryStub(None, None)
    airstrike_conditions = _SimilarRepositoryStub(35, 0.466667)
    service = MatchingService(villages, airstrike_conditions)

    result = service.match(_extraction(village=None, action=verbose_airstrike))

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

    def match(
        self,
        extraction_result: ExtractionResult,
        *,
        cnrs_classification: dict | None = None,
    ) -> MatchResultDTO:
        # MatchIncidentAction passes CNRS context since 8ebac94.
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


def test_action_short_circuits_non_lebanon_raw_text_before_matching() -> None:
    expected = MatchResultDTO(
        village_matches=[
            VillageMatchResult(
                matched_village_id=1519,
                village_confidence=0.62,
                village_match_status=MatchResultStatus.matched,
                village_review_required=False,
                raw_village_text="الشرقية",
            )
        ],
        any_village_low_confidence=False,
        matched_condition_id=1,
        condition_confidence=1.0,
        condition_match_status=MatchResultStatus.matched,
        condition_review_required=False,
        raw_condition_text="Bombs",
    )
    message = SimpleNamespace(
        id=42,
        raw_text=(
            "إطلاق نار من آليات الاحتلال باتجاه المناطق الشرقية "
            "لمشروع بيت لا.هيا شمال قطاع غز.ة"
        ),
        extraction_result=_extraction(
            village=["الشرقية"],
            action="Bombs",
        ).model_dump(mode="json"),
    )
    repository = _RawMessageRepositoryStub(message)
    service = _MatchingServiceStub(expected)

    result = MatchIncidentAction(repository, service).execute(42)

    assert service.received is None
    assert result.village_matches == []
    assert result.condition_match_status == MatchResultStatus.unmatched
    assert result.condition_review_required is True
    assert repository.saved == (message, result)


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
        # Real presence-only text: the eligibility rules must pass it through
        # so routing is actually reached and the retry guard is exercised.
        raw_text="تحليق طيران استطلاعي فوق بلدة عيترون",
        filter_result=None,
        status=MessageStatus.parsed,
        error_message=None,
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


@pytest.mark.parametrize(
    "raw_text",
    [
        "نجاة فريق إسعاف من غارة نفذتها مروحية أباتشي إسرائيلية على مبنى تجاري في ميفدون - شوكين",
        "عاجل | مراسلنا: الطيران المسيّر الاسرائيلي استهدف مدينة النبطية في جنوب لبنان",
    ],
)
def test_post_llm_air_result_is_rematched_to_incident(raw_text: str) -> None:
    air = MatchResultDTO(
        village_matches=[],
        any_village_low_confidence=False,
        matched_condition_id=38,
        condition_confidence=0.9,
        condition_match_status=MatchResultStatus.matched,
        condition_review_required=False,
        raw_condition_text="helicopter",
    )
    incident = air.model_copy(
        update={"matched_condition_id": 5, "raw_condition_text": "Bombs"}
    )

    class _SequentialMatcher:
        def __init__(self) -> None:
            self.calls: list[ExtractionResult] = []

        def match(self, extraction_result, *, cnrs_classification=None):
            self.calls.append(extraction_result)
            return air if len(self.calls) == 1 else incident

    message = SimpleNamespace(
        id=42,
        raw_text=raw_text,
        raw_payload={},
        filter_result=None,
        status=MessageStatus.parsed,
        error_message=None,
        cnrs_classification=None,
        extraction_result=_extraction(action="Helicopter Hovering").model_dump(mode="json"),
    )
    repository = _RawMessageRepositoryStub(message)
    matcher = _SequentialMatcher()
    air_repository = SimpleNamespace(route_from_match=lambda _message, _result: False)

    result = MatchIncidentAction(
        repository, matcher, air_repository  # type: ignore[arg-type]
    ).execute(42)

    assert result.matched_condition_id == 5
    assert matcher.calls[1].action_description == "Bombs"
    assert message.filter_result["air_violation_rerouted"]["matched_terms"]
    assert repository.saved == (message, incident)


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
        conditional_aliases=None,
    ) -> None:
        self.candidates_by_text = candidates_by_text
        self.aliases = aliases or {}
        self.conditional_aliases = conditional_aliases or {}

    def resolve_alias(self, normalized_text: str):
        village = self.aliases.get(normalized_text)
        return (village, 1.0) if village is not None else None

    def find_similar(self, text: str, limit: int = 5):
        return self.candidates_by_text.get(text, [])[:limit]

    def find_geo_conditional_aliases(self, normalized_text: str):
        village = self.conditional_aliases.get(normalized_text)
        return [(village, 1.0)] if village is not None else []


def _geo_village(
    village_id: int,
    ref_name_ar: str,
    coord_x: float,
    coord_y: float,
    caza_ar: str | None = None,
):
    return SimpleNamespace(
        id=village_id,
        ref_name_ar=ref_name_ar,
        caza_ar=caza_ar,
        caza_en=None,
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

    result = service.match(_extraction(village=["حاروف", "زبدين"], action=None))

    assert result.village_matches[0].matched_village_id == harouf.id
    zibdine_match = result.village_matches[1]
    assert zibdine_match.matched_village_id == zibdine_nabatiyeh.id
    assert zibdine_match.village_match_status == MatchResultStatus.matched
    assert zibdine_match.resolved_by_geo_context is True
    assert zibdine_match.geo_context_anchor_village_id == harouf.id
    assert zibdine_match.original_top_candidate_id == zibdine_jbayl.id
    assert zibdine_match.alternate_candidate_village_id == zibdine_jbayl.id


def test_qada_hint_resolves_zibdine_to_nabatiyeh_candidate() -> None:
    zibdine_jbayl = _geo_village(1530, "زبدين", 0, 0, caza_ar="جبيل")
    zibdine_nabatiyeh = _geo_village(
        1529,
        "زبدين النبطية",
        0,
        0,
        caza_ar="النبطية",
    )
    villages = _GeoVillageRepositoryStub(
        {
            "زبدين": [
                (zibdine_jbayl, 1.0),
                (zibdine_nabatiyeh, 0.43),
            ]
        }
    )
    service = MatchingService(villages, _SimilarRepositoryStub(None, None))

    result = service.match(_extraction(village=["زبدين قضاء النبطية"], action=None))

    assert result.village_matches[0].matched_village_id == 1529
    assert result.village_matches[0].village_match_status == MatchResultStatus.matched


def test_raw_9298_qada_qualifier_resolves_zibdine_to_nabatiyeh() -> None:
    zibdine_jbayl = _geo_village(1530, "زبدين", 0, 0, caza_ar="جبيل")
    zibdine_nabatiyeh = _geo_village(
        1529,
        "زبدين النبطية",
        0,
        0,
        caza_ar="النبطية",
    )
    villages = _GeoVillageRepositoryStub(
        {
            "زبدين": [
                (zibdine_jbayl, 1.0),
                (zibdine_nabatiyeh, 0.43),
            ]
        }
    )
    extraction = _extraction(
        village=["زبدين"],
        action=None,
        village_roles=[
            VillageRoleEntry(
                village="زبدين",
                qualifier_text="قضاء النبطية",
            )
        ],
    )

    result = MatchingService(
        villages,
        _SimilarRepositoryStub(None, None),
    ).match(extraction)

    assert result.village_matches[0].matched_village_id == 1529
    assert result.village_matches[0].village_match_status == MatchResultStatus.matched


def test_message_10395_bare_qsair_uses_south_lebanon_geo_anchor() -> None:
    anchor = _geo_village(700, "الطيبة", 0, 0)
    qsair_akkar = _geo_village(900, "القصير", 150000, 0, caza_ar="عكار")
    aadchit_el_qoussair = _geo_village(
        73256,
        "عدشيت القصير",
        5000,
        0,
        caza_ar="مرجعيون",
    )
    villages = _GeoVillageRepositoryStub(
        {
            "القصير": [
                (qsair_akkar, 1.0),
                (aadchit_el_qoussair, 0.42),
            ]
        },
        aliases={"الطيبه": anchor},
    )

    result = MatchingService(
        villages,
        _SimilarRepositoryStub(None, None),
    ).match(_extraction(village=["الطيبة", "القصير"], action=None))

    assert result.village_matches[1].matched_village_id == 73256
    assert result.village_matches[1].resolved_by_geo_context is True


@pytest.mark.parametrize("helta_mention", ["حلتا", "مزرعة حلتا"])
def test_raw_11553_helta_uses_conditional_kfar_chouba_candidate(
    helta_mention: str,
) -> None:
    zawtar = _geo_village(1519, "زوطر الشرقية", 724681, 3689717)
    batroun_helta = _geo_village(675, "حلتا", 755897, 3792122)
    kfar_chouba = _geo_village(813, "كفر شوبا", 750226, 3689888)
    villages = _GeoVillageRepositoryStub(
        {
            "زوطر": [(zawtar, 1.0)],
            normalize_arabic_text(helta_mention): [(batroun_helta, 1.0)],
            "كفرشوبا": [(kfar_chouba, 1.0)],
        },
        conditional_aliases={
            normalize_arabic_text(helta_mention): kfar_chouba,
        },
    )

    result = MatchingService(
        villages,
        _SimilarRepositoryStub(None, None),
    ).match(
        _extraction(
            village=["زوطر", helta_mention],
            action=None,
            village_roles=[
                VillageRoleEntry(village="زوطر"),
                VillageRoleEntry(
                    village=helta_mention,
                    qualifier_text="كفرشوبا",
                ),
            ],
        )
    )

    helta_match = result.village_matches[1]
    assert helta_match.matched_village_id == kfar_chouba.id
    assert helta_match.resolved_by_geo_context is True
    assert helta_match.geo_context_anchor_village_id == kfar_chouba.id
    assert helta_match.original_top_candidate_id == batroun_helta.id
    assert helta_match.alternate_candidate_village_id == batroun_helta.id


def test_standalone_helta_without_southern_anchor_stays_batroun() -> None:
    batroun_helta = _geo_village(675, "حلتا", 755897, 3792122)
    kfar_chouba = _geo_village(813, "كفر شوبا", 750226, 3689888)
    villages = _GeoVillageRepositoryStub(
        {"حلتا": [(batroun_helta, 1.0)]},
        conditional_aliases={"حلتا": kfar_chouba},
    )

    result = MatchingService(
        villages,
        _SimilarRepositoryStub(None, None),
    ).match(_extraction(village=["حلتا"], action=None))

    helta_match = result.village_matches[0]
    assert helta_match.matched_village_id == batroun_helta.id
    assert helta_match.village_match_status == MatchResultStatus.matched_low_confidence
    assert helta_match.resolved_by_geo_context is False


def test_conditional_helta_considers_only_default_and_configured_candidate() -> None:
    anchor = _geo_village(900, "الهبارية", 748000, 3691000)
    batroun_helta = _geo_village(675, "حلتا", 755897, 3792122)
    unrelated_southern = _geo_village(1026, "مزرعة", 748100, 3691100)
    kfar_chouba = _geo_village(813, "كفر شوبا", 750226, 3689888)
    villages = _GeoVillageRepositoryStub(
        {
            "الهباريه": [(anchor, 1.0)],
            "مزرعه حلتا": [
                (batroun_helta, 0.55),
                (unrelated_southern, 0.54),
            ],
        },
        conditional_aliases={"مزرعه حلتا": kfar_chouba},
    )

    result = MatchingService(
        villages,
        _SimilarRepositoryStub(None, None),
    ).match(_extraction(village=["الهبارية", "مزرعة حلتا"], action=None))

    helta_match = result.village_matches[1]
    assert helta_match.matched_village_id == kfar_chouba.id
    assert helta_match.matched_village_id != unrelated_southern.id
    assert helta_match.resolved_by_geo_context is True
    assert helta_match.geo_context_anchor_village_id == anchor.id


def test_sub_event_locations_receive_scoped_conditions() -> None:
    villages = _MultiSimilarRepositoryStub([(101, 1.0), (202, 1.0)])
    conditions = _MultiSimilarRepositoryStub([(5, 1.0)])
    extraction = _extraction(village=[], action="قصف مدفعي")
    extraction = extraction.model_copy(
        update={
            "sub_events": [
                ExtractionSubEvent(
                    locations=[
                        VillageRoleEntry(village="المنصوري", role=VillageRole.target),
                    ],
                    action_description="قصف مدفعي",
                    evidence_span="قصف مدفعي يستهدف بلدة المنصوري",
                    casualties=ExtractionCasualties(),
                )
            ]
        }
    )
    service = MatchingService(villages, conditions)

    result = service.match(extraction)

    assert len(result.village_matches) == 1
    assert result.village_matches[0].matched_condition_id == 5
    assert result.village_matches[0].event_index == 0


def test_sub_event_locations_fall_back_to_matched_root_condition() -> None:
    villages = _MultiSimilarRepositoryStub([(976, 1.0), (1153, 0.9)])
    conditions = _TextSimilarRepositoryStub(
        {
            # The mention is passed as-is; the real repository lower()s English
            # labels in SQL, so the stub is keyed by the text actually sent.
            "Bombs": [(SimpleNamespace(id=46), 1.0)],
            normalize_arabic_text(
                "اغار الطيران الحربي المعادي مستهدفا المنصوري والنبطية الفوقا"
            ): [],
        }
    )
    extraction = _extraction(village=[], action="Bombs")
    extraction = extraction.model_copy(
        update={
            "sub_events": [
                ExtractionSubEvent(
                    locations=[
                        VillageRoleEntry(village="المنصوري", role=VillageRole.target),
                        VillageRoleEntry(
                            village="النبطية الفوقا",
                            role=VillageRole.target,
                        ),
                    ],
                    action_description=(
                        "اغار الطيران الحربي المعادي مستهدفا المنصوري والنبطية الفوقا"
                    ),
                    evidence_span=(
                        "اغار الطيران الحربي المعادي مستهدفا المنصوري والنبطية الفوقا"
                    ),
                    casualties=ExtractionCasualties(),
                )
            ]
        }
    )

    result = MatchingService(villages, conditions).match(extraction)

    assert len(result.village_matches) == 2
    assert {match.matched_condition_id for match in result.village_matches} == {46}
    assert {
        match.condition_match_status for match in result.village_matches
    } == {MatchResultStatus.matched}


def test_exact_duplicate_without_anchor_keeps_low_confidence_winner() -> None:
    first = _geo_village(100, "كنيسة", 0, 0)
    second = _geo_village(200, "كنيسة", 100000, 100000)
    villages = _GeoVillageRepositoryStub({"كنيسه": [(first, 1.0), (second, 1.0)]})
    service = MatchingService(villages, _SimilarRepositoryStub(None, None))

    result = service.match(_extraction(village=["كنيسة"], action=None))

    village_match = result.village_matches[0]
    assert village_match.matched_village_id == first.id
    assert (
        village_match.village_match_status == MatchResultStatus.matched_low_confidence
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
        village_match.village_match_status == MatchResultStatus.matched_low_confidence
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

    result = service.match(_extraction(village=["مرساة", "قرية"], action=None))

    village_match = result.village_matches[1]
    assert village_match.matched_village_id == original.id
    assert (
        village_match.village_match_status == MatchResultStatus.matched_low_confidence
    )
    assert village_match.resolved_by_geo_context is False


def _named_village(village_id: int, ref_name_ar: str):
    return SimpleNamespace(
        id=village_id,
        ref_name_ar=ref_name_ar,
        acs_name=None,
        cad_name=None,
        caza_ar=None,
        caza_en=None,
        coord_x=None,
        coord_y=None,
    )


def test_leading_descriptor_is_stripped_and_raw_mention_is_kept() -> None:
    mayfadoun = _named_village(1003, "ميفدون")
    villages = _GeoVillageRepositoryStub(
        {
            "اطراف ميفدون": [(mayfadoun, 0.30)],
            "ميفدون": [(mayfadoun, 0.90)],
        }
    )

    result = MatchingService(villages, _SimilarRepositoryStub(None, None)).match(
        _extraction(village=["أطراف ميفدون"], action=None)
    )

    vm = result.village_matches[0]
    assert vm.matched_village_id == 1003
    assert vm.village_match_status == MatchResultStatus.matched
    assert vm.raw_village_text == "أطراف ميفدون"


def test_descriptor_before_an_ambiguous_name_stays_flagged() -> None:
    first = _named_village(1, "نبطية الفوقا")
    second = _named_village(2, "نبطية التحتا")
    villages = _GeoVillageRepositoryStub(
        {"حي النبطيه": [], "النبطيه": [(first, 0.50), (second, 0.50)]}
    )

    result = MatchingService(villages, _SimilarRepositoryStub(None, None)).match(
        _extraction(village=["حي النبطية"], action=None)
    )

    vm = result.village_matches[0]
    assert vm.village_match_status == MatchResultStatus.matched_low_confidence
    assert vm.village_review_required is True


def test_real_name_that_starts_with_a_descriptor_still_matches_as_written() -> None:
    industrial = _named_village(9, "مدينة الصناعية")
    other = _named_village(10, "الصناعية")
    villages = _GeoVillageRepositoryStub(
        {
            "مدينه الصناعيه": [(industrial, 1.0)],
            "الصناعيه": [(other, 0.60)],
        }
    )

    result = MatchingService(villages, _SimilarRepositoryStub(None, None)).match(
        _extraction(village=["مدينة الصناعية"], action=None)
    )

    assert result.village_matches[0].matched_village_id == 9


def test_mention_that_is_only_a_descriptor_is_not_emptied() -> None:
    villages = _GeoVillageRepositoryStub({"اطراف": []})

    result = MatchingService(villages, _SimilarRepositoryStub(None, None)).match(
        _extraction(village=["أطراف"], action=None)
    )

    assert result.village_matches[0].matched_village_id is None


def _match_one(mention: str, candidates: dict):
    villages = _GeoVillageRepositoryStub(candidates)
    result = MatchingService(villages, _SimilarRepositoryStub(None, None)).match(
        _extraction(village=[mention], action=None)
    )
    return result.village_matches[0]


def test_tie_between_distinct_villages_is_flagged_even_below_old_threshold() -> None:
    east = _named_village(1519, "زوطر الشرقية")
    west = _named_village(1520, "زوطر الغربية")

    vm = _match_one("زوطر", {"زوطر": [(east, 0.53), (west, 0.53)]})

    assert vm.village_match_status == MatchResultStatus.matched_low_confidence
    assert vm.village_review_required is True


def test_clear_best_match_below_old_threshold_is_accepted_with_a_note() -> None:
    village = _named_village(5, "كفر شوبا")
    other = _named_village(6, "كفر")

    vm = _match_one("كفرشوبا", {"كفرشوبا": [(village, 0.55), (other, 0.40)]})

    assert vm.matched_village_id == 5
    assert vm.village_match_status == MatchResultStatus.matched
    assert vm.village_review_required is False
    assert vm.village_match_note is not None
    assert vm.village_match_method in {"compact", "normalized", "trigram"}


def test_best_score_under_the_floor_is_flagged() -> None:
    village = _named_village(5, "حلتا")

    vm = _match_one("حالتا", {"حالتا": [(village, 0.45)]})

    assert vm.village_match_status == MatchResultStatus.matched_low_confidence


def test_exact_name_wins_over_longer_names_that_contain_it() -> None:
    sour = _named_village(1407, "صور")
    neiha = _named_village(1176, "نيحا صور")
    bayad = _named_village(310, "البياض صور")

    vm = _match_one("صور", {"صور": [(sour, 1.0), (neiha, 0.44), (bayad, 0.44)]})

    assert vm.matched_village_id == 1407
    assert vm.village_match_status == MatchResultStatus.matched
    assert vm.village_match_method == "exact"
    assert vm.village_match_note is None


def test_two_villages_with_the_same_exact_name_stay_flagged() -> None:
    first = _named_village(100, "الطيبة")
    second = _named_village(200, "الطيبة")

    vm = _match_one("الطيبة", {"الطيبه": [(first, 1.0), (second, 1.0)]})

    assert vm.village_match_status == MatchResultStatus.matched_low_confidence
    assert vm.village_review_required is True


def test_parent_and_child_names_are_not_a_tie() -> None:
    parent = _named_village(1, "الخيام")
    child = _named_village(2, "مدينة الخيام")

    vm = _match_one("خيام", {"خيام": [(parent, 0.55), (child, 0.53)]})

    assert vm.village_match_status == MatchResultStatus.matched
    assert vm.matched_village_id == 1


def test_definite_article_variant_is_a_normalized_match() -> None:
    ramadiyeh = _named_village(1324, "رمادية")

    vm = _match_one("الرمادية", {"الراديه": [], "الماديه": [], "الرماديه": [(ramadiyeh, 1.0)]})

    assert vm.matched_village_id == 1324
    assert vm.village_match_status == MatchResultStatus.matched
    assert vm.village_match_method == "normalized"


def test_no_candidate_stays_unmatched_and_flagged() -> None:
    vm = _match_one("قرية غير موجودة", {})

    assert vm.matched_village_id is None
    assert vm.village_match_status == MatchResultStatus.unmatched
    assert vm.village_review_required is True


def test_alias_match_records_alias_method() -> None:
    touline = _named_village(1464, "تولين")
    villages = _GeoVillageRepositoryStub({}, aliases={"وادي السلوقي": touline})

    result = MatchingService(villages, _SimilarRepositoryStub(None, None)).match(
        _extraction(village=["وادي السلوقي"], action=None)
    )

    assert result.village_matches[0].village_match_method == "alias"


def _ambiguity_extraction(evidence, alternatives):
    from app.llm.dtos import VillageRoleEntry

    return _extraction(
        village=["مجدل زون", "الخيام"],
        action=None,
        village_roles=[
            VillageRoleEntry(village="مجدل زون"),
            VillageRoleEntry(village="الخيام"),
        ],
    ).model_copy(
        update={
            "location_ambiguity": True,
            "location_alternatives": alternatives,
            "location_ambiguity_evidence": evidence,
        }
    )


def test_location_ambiguity_downgrades_only_the_named_village() -> None:
    result = MatchingService(
        _SimilarRepositoryStub(7, 0.9), _SimilarRepositoryStub(None, None)
    ).match(_ambiguity_extraction("محيط مجدل زون وبيوت السياد", ["بيوت السياد"]))

    by_name = {vm.raw_village_text: vm for vm in result.village_matches}
    assert (
        by_name["مجدل زون"].village_match_status
        == MatchResultStatus.matched_low_confidence
    )
    assert by_name["الخيام"].village_match_status == MatchResultStatus.matched
    assert result.any_village_low_confidence is True


def test_location_ambiguity_without_a_locatable_village_downgrades_all() -> None:
    result = MatchingService(
        _SimilarRepositoryStub(7, 0.9), _SimilarRepositoryStub(None, None)
    ).match(_ambiguity_extraction(None, []))

    assert all(
        vm.village_match_status == MatchResultStatus.matched_low_confidence
        for vm in result.village_matches
    )


def test_geo_context_resolution_records_the_geo_context_method() -> None:
    harouf = _geo_village(652, "حروف", 727118.662568, 3695226.05415)
    zibdine_jbayl = _geo_village(1530, "زبدين", 749917.749312, 3776011.05529)
    zibdine_nabatiyeh = _geo_village(
        1529, "زبدين النبطية", 729089.964486, 3695394.05526
    )
    villages = _GeoVillageRepositoryStub(
        {"زبدين": [(zibdine_jbayl, 1.0), (zibdine_nabatiyeh, 0.42857143)]},
        aliases={"حاروف": harouf},
    )

    result = MatchingService(villages, _SimilarRepositoryStub(None, None)).match(
        _extraction(village=["حاروف", "زبدين"], action=None)
    )

    assert result.village_matches[0].village_match_method == "alias"
    assert result.village_matches[1].resolved_by_geo_context is True
    assert result.village_matches[1].village_match_method == "geo_context"


@pytest.mark.parametrize(
    ("mention", "normalized", "wrong_village"),
    [
        ("الناصرة", "الناصره", "الناقورة"),
        ("خان يونس", "خان يونس", "بيت يونس"),
    ],
)
def test_known_foreign_place_is_not_matched_to_a_lebanese_village(
    mention: str, normalized: str, wrong_village: str
) -> None:
    village = _named_village(335, wrong_village)

    vm = _match_one(mention, {normalized: [(village, 0.42)]})

    assert vm.matched_village_id is None
    assert vm.village_match_status == MatchResultStatus.unmatched
    assert vm.village_review_required is True


def test_foreign_place_name_with_an_exact_lebanese_homonym_still_matches() -> None:
    homs = _named_village(4242, "حمص")

    vm = _match_one("حمص", {"حمص": [(homs, 1.0)]})

    assert vm.matched_village_id == 4242
    assert vm.village_match_status == MatchResultStatus.matched


def test_shared_letters_do_not_count_as_lexical_overlap() -> None:
    """A confident-looking score against a name that only contains the mention's
    letters must not be trusted ("مرج" is not مرجعيون)."""
    marjayoun = _named_village(9, "مرجعيون")

    vm = _match_one("مرج", {"مرج": [(marjayoun, 0.70)]})

    assert vm.village_match_status == MatchResultStatus.matched_low_confidence


def test_shared_whole_word_still_counts_as_lexical_overlap() -> None:
    village = _named_village(9, "عين الرمانة")

    vm = _match_one("رمانة", {"رمانه": [(village, 0.70)]})

    assert vm.village_match_status == MatchResultStatus.matched


@pytest.mark.parametrize(
    ("mention", "exact_id", "rivals"),
    [
        ("بعلبك", 186, ["راس بعلبك", "طيبة بعلبك"]),
        ("جنين", 732, ["جب جنين", "دير جنين"]),
    ],
)
def test_exact_name_wins_for_baalbek_and_jenin(
    mention: str, exact_id: int, rivals: list[str]
) -> None:
    exact = _named_village(exact_id, mention)
    others = [
        (_named_village(1000 + index, name), 0.55)
        for index, name in enumerate(rivals)
    ]

    vm = _match_one(mention, {mention: [(exact, 1.0), *others]})

    assert vm.matched_village_id == exact_id
    assert vm.village_match_status == MatchResultStatus.matched


def test_bare_name_next_to_a_region_suffixed_twin_stays_reviewable() -> None:
    """عرمون / عرمون كسروان are the same name in two regions; without an anchor
    this is a real ambiguity, so it is not resolved by the exact-name rule."""
    aramoun = _named_village(121, "عرمون")
    keserwan = _named_village(122, "عرمون كسروان")

    vm = _match_one("عرمون", {"عرمون": [(aramoun, 1.0), (keserwan, 0.46)]})

    assert vm.matched_village_id == 121
    assert vm.village_match_status == MatchResultStatus.matched_low_confidence


def test_geo_context_does_not_promote_a_nearer_candidate_that_misses_the_mention() -> None:
    anchor = _geo_village(10, "مرساة", 0, 0)
    far_top = _geo_village(20, "مزرعة", 100000, 0)
    near_unrelated = _geo_village(30, "مزرعة طمره", 1000, 0)
    villages = _GeoVillageRepositoryStub(
        {"مزرعه بسطره": [(far_top, 0.50), (near_unrelated, 0.44)]},
        aliases={"مرساة": anchor},
    )

    result = MatchingService(villages, _SimilarRepositoryStub(None, None)).match(
        _extraction(village=["مرساة", "مزرعة بسطرة"], action=None)
    )

    village_match = result.village_matches[1]
    assert village_match.resolved_by_geo_context is False
    assert village_match.matched_village_id != near_unrelated.id
    assert village_match.village_match_status == MatchResultStatus.matched_low_confidence


def test_partial_word_cover_below_old_threshold_stays_flagged() -> None:
    castle = _named_village(1222, "القلعة")
    other = _named_village(17, "عدشيت الشقيف")

    vm = _match_one("قلعة الشقيف", {"قلعه الشقيف": [(castle, 0.55), (other, 0.39)]})

    assert vm.village_match_status == MatchResultStatus.matched_low_confidence


def test_descriptor_with_definite_article_is_stripped() -> None:
    khiam = _named_village(901, "الخيام")
    villages = _GeoVillageRepositoryStub(
        {"المدينه الخيام": [(khiam, 0.53)], "الخيام": [(khiam, 1.0)]}
    )

    result = MatchingService(villages, _SimilarRepositoryStub(None, None)).match(
        _extraction(village=["المدينة الخيام"], action=None)
    )

    assert result.village_matches[0].village_match_status == MatchResultStatus.matched
    assert result.village_matches[0].raw_village_text == "المدينة الخيام"


def test_descriptor_normalization_records_original_text() -> None:
    mayfadoun = _named_village(1003, "ميفدون")
    villages = _GeoVillageRepositoryStub(
        {
            "خراج ميفدون": [(mayfadoun, 0.30)],
            "ميفدون": [(mayfadoun, 1.0)],
        }
    )

    result = MatchingService(villages, _SimilarRepositoryStub(None, None)).match(
        _extraction(village=["خراج ميفدون"], action=None)
    )

    vm = result.village_matches[0]
    assert vm.matched_village_id == mayfadoun.id
    assert vm.normalized_from == "خراج ميفدون"


def test_neighborhood_dash_prefers_city_after_dash() -> None:
    nabatieh = _named_village(71111, "النبطية")
    neighborhood = _named_village(999, "حي السلام")
    villages = _GeoVillageRepositoryStub(
        {
            "حي السلام النبطيه": [(neighborhood, 0.52)],
            "النبطيه": [(nabatieh, 1.0)],
        }
    )

    result = MatchingService(villages, _SimilarRepositoryStub(None, None)).match(
        _extraction(village=["حي السلام - النبطية"], action=None)
    )

    vm = result.village_matches[0]
    assert vm.matched_village_id == nabatieh.id
    assert vm.normalized_from == "حي السلام - النبطيه"


def test_resolvable_conjunction_splits_into_two_locations() -> None:
    hadatha = _named_village(1, "حداثا")
    harees = _named_village(2, "حاريص")
    villages = _GeoVillageRepositoryStub(
        {
            "حداثا": [(hadatha, 1.0)],
            "حاريص": [(harees, 1.0)],
        }
    )

    result = MatchingService(villages, _SimilarRepositoryStub(None, None)).match(
        _extraction(village=["حداثا وحاريص"], action=None)
    )

    assert [match.raw_village_text for match in result.village_matches] == [
        "حداثا",
        "حاريص",
    ]
    assert [match.matched_village_id for match in result.village_matches] == [1, 2]


def test_geo_context_keeps_review_when_two_candidates_are_near_anchor() -> None:
    anchor = _geo_village(10, "النبطية", 0, 0)
    east = _geo_village(1519, "زوطر الشرقية", 10000, 0)
    west = _geo_village(1520, "زوطر الغربية", 11000, 0)
    villages = _GeoVillageRepositoryStub(
        {"زوطر": [(east, 0.53), (west, 0.53)]},
        aliases={"النبطيه": anchor},
    )

    result = MatchingService(villages, _SimilarRepositoryStub(None, None)).match(
        _extraction(village=["النبطية", "زوطر"], action=None)
    )

    vm = result.village_matches[1]
    assert vm.village_match_status == MatchResultStatus.matched_low_confidence
    assert vm.resolved_by_geo_context is False
