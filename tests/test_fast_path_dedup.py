from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.news.repositories.incident_repository import FastDedupCandidate
from app.news.services.dedup.duplicate_comparison_service import (
    DuplicateComparisonConfig,
    DuplicateComparisonService,
)
from app.news.services.dedup.fast_path_dedup import (
    FastPathDedupOutcome,
    FastPathDedupService,
)

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

_MSG_DT = datetime(2026, 8, 18, 11, 0, tzinfo=timezone.utc)


class _IncidentRepoStub:
    def __init__(self, candidates: list[FastDedupCandidate] | None = None) -> None:
        self.candidates = candidates or []
        self.last_query: dict | None = None

    def find_fast_dedup_candidates(self, **kwargs):
        self.last_query = kwargs
        return list(self.candidates)


def _service(repo: _IncidentRepoStub) -> FastPathDedupService:
    return FastPathDedupService(repo, DuplicateComparisonService(_CONFIG))


def _candidate(*, gap: float, text: float | None, embedding: float | None = None):
    return FastDedupCandidate(
        incident=SimpleNamespace(id=uuid4(), raw_message_id=100),
        time_gap_seconds=gap,
        text_similarity=text,
        embedding_similarity=embedding,
    )


def _decide(service: FastPathDedupService, **overrides):
    kwargs = dict(
        village_match_status="matched",
        condition_match_status="matched",
        village_id=42,
        condition_id=7,
        message_datetime=_MSG_DT,
        candidate_text="قصف على الخيام",
        candidate_embedding=None,
        exclude_raw_message_id=200,
    )
    kwargs.update(overrides)
    return service.decide_for_village(**kwargs)


def test_confident_duplicate_on_high_confidence_verdict() -> None:
    repo = _IncidentRepoStub([_candidate(gap=90, text=0.88)])
    service = _service(repo)

    decision = _decide(service)

    assert decision.outcome == FastPathDedupOutcome.confident_duplicate
    assert decision.representative_raw_message_id == 100
    assert decision.similarity_method == "text"
    assert repo.last_query["village_id"] == 42
    assert repo.last_query["condition_id"] == 7
    assert repo.last_query["lookup_window_days"] == 7
    assert repo.last_query["exclude_raw_message_id"] == 200


def test_possible_duplicate_on_mid_tier_verdict() -> None:
    repo = _IncidentRepoStub([_candidate(gap=10 * 60, text=0.70)])
    decision = _decide(_service(repo))

    assert decision.outcome == FastPathDedupOutcome.possible_duplicate
    assert decision.matched_incident is not None


def test_materialize_when_no_candidates() -> None:
    decision = _decide(_service(_IncidentRepoStub([])))
    assert decision.outcome == FastPathDedupOutcome.materialize


def test_materialize_when_all_candidates_are_distinct() -> None:
    # Mansouri-style: ~88h gap, low similarity -> distinct -> materialize.
    repo = _IncidentRepoStub(
        [
            _candidate(gap=88 * 3600, text=0.19),
            _candidate(gap=94 * 3600, text=0.57, embedding=0.60),
        ]
    )
    decision = _decide(_service(repo))
    assert decision.outcome == FastPathDedupOutcome.materialize


def test_high_confidence_wins_over_a_closer_possible() -> None:
    repo = _IncidentRepoStub(
        [
            _candidate(gap=60, text=0.50),          # possible
            _candidate(gap=20 * 60, text=0.95),     # high confidence
        ]
    )
    decision = _decide(_service(repo))
    assert decision.outcome == FastPathDedupOutcome.confident_duplicate


def test_low_confidence_village_never_fast_dedups() -> None:
    repo = _IncidentRepoStub([_candidate(gap=30, text=0.99)])
    decision = _decide(_service(repo), village_match_status="matched_low_confidence")
    assert decision.outcome == FastPathDedupOutcome.materialize
    assert repo.last_query is None


def test_skip_ineligible_when_village_unmatched() -> None:
    repo = _IncidentRepoStub()
    decision = _decide(_service(repo), village_match_status="unmatched", village_id=None)
    assert decision.outcome == FastPathDedupOutcome.skip_ineligible
    assert repo.last_query is None


def test_embedding_substitutes_for_missing_text() -> None:
    repo = _IncidentRepoStub([_candidate(gap=90, text=None, embedding=0.90)])
    decision = _decide(_service(repo), candidate_text=None, candidate_embedding=[0.1])
    assert decision.outcome == FastPathDedupOutcome.confident_duplicate
    assert decision.similarity_method == "embedding"


def test_nabatiyeh_style_same_village_flags_duplicate_split_village_does_not() -> None:
    """Nabatiyeh-style set: ~2min gaps + high similarity → duplicate for the four
    rows sharing matched village_id. The fifth (split-village) row is an expected
    gap — same village/condition precondition fails across village_id 703 vs 1153,
    so fast-path never consults the comparison service for cross-id merges.
    """
    shared_village_id = 703  # e.g. Nabatiyeh El-Tahta / matched canonical
    split_village_id = 1153  # Houmine/Nabatiyeh El-Faouka split — do not merge here
    condition_id = 12

    # Four near-duplicate candidates already materialized under village 703.
    near_dupe = _candidate(gap=90, text=0.91)
    repo_same = _IncidentRepoStub([near_dupe])
    for _ in range(4):
        decision = _decide(
            _service(repo_same),
            village_id=shared_village_id,
            condition_id=condition_id,
        )
        assert decision.outcome == FastPathDedupOutcome.confident_duplicate
        assert repo_same.last_query["village_id"] == shared_village_id

    # Fifth row resolved to the other half of the split village: lookup is scoped
    # by village_id, so the 703 incidents are not candidates (assert the gap).
    repo_split = _IncidentRepoStub([])  # no same-village_id candidates returned
    decision_split = _decide(
        _service(repo_split),
        village_id=split_village_id,
        condition_id=condition_id,
    )
    assert decision_split.outcome == FastPathDedupOutcome.materialize
    assert repo_split.last_query["village_id"] == split_village_id
    assert repo_split.last_query["village_id"] != shared_village_id
