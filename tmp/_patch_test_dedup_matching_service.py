from datetime import date, time
from types import SimpleNamespace
from uuid import uuid4

from app.news.services.dedup_matching_service import DedupMatchingService
from app.news.services.duplicate_comparison_service import (
    DuplicateComparisonConfig,
    DuplicateComparisonService,
)


class _IncidentRepositoryStub:
    def __init__(self, candidates: list[object]) -> None:
        self.candidates = candidates
        self.calls: list[dict] = []

    def list_duplicate_candidates(
        self,
        *,
        village_id: int,
        event_date: date,
        khabar_embedding: list[float],
        window_days: int,
        exclude_raw_message_id: int | None = None,
    ) -> list[tuple[object, float]]:
        self.calls.append(
            {
                "village_id": village_id,
                "event_date": event_date,
                "khabar_embedding": khabar_embedding,
                "window_days": window_days,
                "exclude_raw_message_id": exclude_raw_message_id,
            }
        )
        return [
            (candidate, candidate.embedding_similarity)
            for candidate in self.candidates
            if candidate.village_id == village_id
            and candidate.raw_message_id != exclude_raw_message_id
        ]


_CONFIG = DuplicateComparisonConfig(
    lookup_window_days=7,
    gap_near_seconds=120,
    gap_mid_seconds=1800,
    gap_far_seconds=21600,
    text_near=0.38,
    text_mid=0.65,
    text_high=0.80,
    embedding_possible=0.78,
    embedding_high=0.86,
)


def _service(repo: _IncidentRepositoryStub) -> DedupMatchingService:
    return DedupMatchingService(
        repo,  # type: ignore[arg-type]
        DuplicateComparisonService(_CONFIG),
    )


def _incident(
    *,
    raw_message_id: int,
    village_id: int = 976,
    condition_id: int = 5,
    event_date: date = date(2026, 8, 28),
    event_time: time | None = time(9, 0),
    embedding_similarity: float = 1.0,
):
    return SimpleNamespace(
        id=uuid4(),
        raw_message_id=raw_message_id,
        village_id=village_id,
        condition_id=condition_id,
        event_date=event_date,
        event_time=event_time,
        embedding_similarity=embedding_similarity,
    )


def test_find_best_match_ignores_same_raw_message_sibling() -> None:
    sibling = _incident(raw_message_id=42, village_id=976)
    different_village_sibling = _incident(raw_message_id=42, village_id=977)
    repo = _IncidentRepositoryStub([sibling, different_village_sibling])
    service = _service(repo)

    existing, score = service.find_best_match(
        village_id=976,
        condition_id=5,
        event_date=date(2026, 8, 28),
        khabar_embedding=[0.1, 0.2, 0.3],
        exclude_raw_message_id=42,
    )

    assert existing is None
    assert score == 0.0
    assert repo.calls[0]["exclude_raw_message_id"] == 42
    assert repo.calls[0]["window_days"] == 7


def test_find_best_match_still_matches_different_bulletins() -> None:
    sibling = _incident(raw_message_id=42, village_id=976)
    different_bulletin = _incident(
        raw_message_id=99, village_id=976, embedding_similarity=0.95
    )
    repo = _IncidentRepositoryStub([sibling, different_bulletin])
    service = _service(repo)

    existing, score = service.find_best_match(
        village_id=976,
        condition_id=5,
        event_date=date(2026, 8, 28),
        event_time=time(9, 1),
        khabar_embedding=[0.1, 0.2, 0.3],
        exclude_raw_message_id=42,
    )

    assert existing is different_bulletin
    assert score >= 0.86


def test_mansouri_style_gap_is_distinct_despite_high_embedding() -> None:
    older = _incident(
        raw_message_id=3336,
        event_date=date(2026, 9, 3),
        event_time=time(9, 21, 24),
        embedding_similarity=0.795,
    )
    repo = _IncidentRepositoryStub([older])
    service = _service(repo)

    existing, score = service.find_best_match(
        village_id=976,
        condition_id=5,
        event_date=date(2026, 9, 6),
        event_time=time(20, 42, 34),
        khabar_embedding=[0.1, 0.2, 0.3],
        exclude_raw_message_id=4236,
    )

    assert existing is None
    assert score == 0.0


def test_different_condition_id_is_never_compared() -> None:
    other_condition = _incident(
        raw_message_id=99, condition_id=20, embedding_similarity=0.99
    )
    repo = _IncidentRepositoryStub([other_condition])
    service = _service(repo)

    existing, score = service.find_best_match(
        village_id=976,
        condition_id=5,
        event_date=date(2026, 8, 28),
        khabar_embedding=[0.1],
        exclude_raw_message_id=1,
    )

    assert existing is None
    assert score == 0.0
