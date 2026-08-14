from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.news.actions.match_incident_action import MatchIncidentAction
from app.llm.dtos import ExtractionResult
from app.news.dtos import (
    MatchResultDTO,
    MatchResultStatus,
)
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
    village: str | None = "  أَيْتَا الشَّعْب  ",
    action: str | None = "غارة جوية",
) -> ExtractionResult:
    return ExtractionResult(
        is_relevant=True,
        village=village,
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

    assert result.matched_village_id == expected_id
    assert result.village_confidence == score
    assert result.village_match_status == status
    assert result.village_review_required is review_required
    assert villages.calls == [("ايتا الشعب", 5)]


def test_matches_condition_and_preserves_raw_mentions() -> None:
    villages = _SimilarRepositoryStub(None, None)
    conditions = _SimilarRepositoryStub(22, 0.81)
    service = MatchingService(villages, conditions)
    extraction = _extraction(village=None, action="غارة جوية")

    result = service.match(extraction)

    assert result.matched_condition_id == 22
    assert result.condition_match_status == MatchResultStatus.matched
    assert result.condition_review_required is False
    assert result.raw_village_text is None
    assert result.raw_condition_text == "غارة جوية"
    assert villages.calls == []


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
        matched_village_id=11,
        village_confidence=0.7,
        village_match_status=MatchResultStatus.matched,
        village_review_required=False,
        raw_village_text="بنت جبيل",
        matched_condition_id=None,
        condition_confidence=0.2,
        condition_match_status=MatchResultStatus.unmatched,
        condition_review_required=True,
        raw_condition_text="حدث غير معروف",
    )
    message = SimpleNamespace(
        id=42,
        extraction_result=_extraction(
            village="بنت جبيل",
            action="حدث غير معروف",
        ).model_dump(mode="json"),
    )
    repository = _RawMessageRepositoryStub(message)
    service = _MatchingServiceStub(expected)

    result = MatchIncidentAction(repository, service).execute(42)

    assert result == expected
    assert service.received is not None
    assert service.received.village == "بنت جبيل"
    assert repository.saved == (message, expected)


def test_action_rejects_message_without_extraction_result() -> None:
    repository = _RawMessageRepositoryStub(
        SimpleNamespace(id=42, extraction_result=None)
    )
    service = _MatchingServiceStub(None)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="has no extraction_result"):
        MatchIncidentAction(repository, service).execute(42)
