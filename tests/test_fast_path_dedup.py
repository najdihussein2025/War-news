from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

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
    cross_village_text_min=0.87,
)

_MSG_DT = datetime(2026, 8, 18, 11, 0, tzinfo=timezone.utc)


class _IncidentRepoStub:
    def __init__(
        self,
        candidates: list[FastDedupCandidate] | None = None,
        cross_candidates: list[FastDedupCandidate] | None = None,
    ) -> None:
        self.candidates = candidates or []
        self.cross_candidates = cross_candidates or []
        self.last_query: dict | None = None
        self.last_cross_query: dict | None = None

    def find_fast_dedup_candidates(self, **kwargs):
        self.last_query = kwargs
        return list(self.candidates)

    def find_cross_village_dedup_candidates(self, **kwargs):
        self.last_cross_query = kwargs
        return list(self.cross_candidates)


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


def test_semantic_match_inside_30_minutes_is_confident_duplicate() -> None:
    repo = _IncidentRepoStub([_candidate(gap=10 * 60, text=0.70)])
    decision = _decide(_service(repo))

    assert decision.outcome == FastPathDedupOutcome.confident_duplicate
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


def test_low_confidence_match_metadata_still_uses_canonical_ids() -> None:
    cross = _candidate(gap=90, text=0.875)
    repo = _IncidentRepoStub([_candidate(gap=30, text=0.99)], cross_candidates=[cross])
    decision = _decide(_service(repo), village_match_status="matched_low_confidence")
    assert decision.outcome == FastPathDedupOutcome.confident_duplicate
    assert repo.last_query is not None
    assert repo.last_cross_query is None


def test_low_confidence_village_materializes_when_cross_village_misses() -> None:
    repo = _IncidentRepoStub([], cross_candidates=[])
    decision = _decide(_service(repo), village_match_status="matched_low_confidence")
    assert decision.outcome == FastPathDedupOutcome.materialize
    assert repo.last_query is not None


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


def test_nabatiyeh_style_same_village_flags_duplicate_split_village_cross_flags() -> None:
    """Same village_id still auto-merges; split village_id now flags possible_duplicate
    at elevated similarity (recon 0.875) instead of silently materializing.
    """
    shared_village_id = 703
    split_village_id = 1153
    condition_id = 12

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

    cross_hit = _candidate(gap=120, text=0.875)
    repo_split = _IncidentRepoStub([], cross_candidates=[cross_hit])
    decision_split = _decide(
        _service(repo_split),
        village_id=split_village_id,
        condition_id=condition_id,
    )
    assert decision_split.outcome == FastPathDedupOutcome.possible_duplicate
    assert decision_split.similarity_score == pytest.approx(0.875)
    assert repo_split.last_cross_query["village_id"] == split_village_id
    assert repo_split.last_cross_query["min_text_similarity"] == 0.87


def test_cross_village_never_returns_confident_duplicate() -> None:
    # Even at 0.99 text, cross-village path is review-only.
    cross = _candidate(gap=60, text=0.99)
    repo = _IncidentRepoStub([], cross_candidates=[cross])
    decision = _decide(_service(repo), village_id=995, condition_id=1)
    assert decision.outcome == FastPathDedupOutcome.possible_duplicate
    assert decision.outcome != FastPathDedupOutcome.confident_duplicate


def test_cross_village_below_elevated_threshold_stays_materialize() -> None:
    # 0.80 would be high_confidence same-village; cross-village requires 0.87.
    cross = _candidate(gap=60, text=0.80)
    repo = _IncidentRepoStub([], cross_candidates=[cross])
    # Stub still returns the row; comparison service must reject it.
    decision = _decide(_service(repo), village_id=995, condition_id=1)
    assert decision.outcome == FastPathDedupOutcome.materialize
