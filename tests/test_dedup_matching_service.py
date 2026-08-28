from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from app.news.services.dedup_matching_service import DedupMatchingService


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
            (candidate, 1.0)
            for candidate in self.candidates
            if candidate.village_id == village_id
            and candidate.raw_message_id != exclude_raw_message_id
        ]


def _incident(*, raw_message_id: int, village_id: int = 976):
    return SimpleNamespace(
        id=uuid4(),
        raw_message_id=raw_message_id,
        village_id=village_id,
        condition_id=5,
        event_date=date(2026, 8, 28),
    )


def test_find_best_match_ignores_same_raw_message_sibling() -> None:
    sibling = _incident(raw_message_id=42, village_id=976)
    different_village_sibling = _incident(raw_message_id=42, village_id=977)
    repo = _IncidentRepositoryStub([sibling, different_village_sibling])
    service = DedupMatchingService(repo)  # type: ignore[arg-type]

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


def test_find_best_match_still_matches_different_bulletins() -> None:
    sibling = _incident(raw_message_id=42, village_id=976)
    different_bulletin = _incident(raw_message_id=99, village_id=976)
    repo = _IncidentRepositoryStub([sibling, different_bulletin])
    service = DedupMatchingService(repo)  # type: ignore[arg-type]

    existing, score = service.find_best_match(
        village_id=976,
        condition_id=5,
        event_date=date(2026, 8, 28),
        khabar_embedding=[0.1, 0.2, 0.3],
        exclude_raw_message_id=42,
    )

    assert existing is different_bulletin
    assert score > 0.0
