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
from app.news.services.matching_service import MatchingService


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
                VillageRoleEntry(village="المنصوري", role=VillageRole.target),
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
