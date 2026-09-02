from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.news.services.pipeline_health_service import PipelineHealthService

_STAGE_ORDER = [
    "relevance_filter",
    "pre_extraction_dedup",
    "tier1_extraction",
    "matching",
    "fast_path",
    "tier2_detail_fill",
    "embedding",
    "materialization",
]


class _Row:
    def __init__(self, pair) -> None:
        self._pair = pair

    def one(self):
        return self._pair


class _StubSession:
    """Returns a queued (count, oldest_ts) pair for each aggregate query."""

    def __init__(self, pairs: list[tuple[int, datetime | None]]) -> None:
        self._pairs = list(pairs)
        self.calls = 0

    def execute(self, _stmt):
        self.calls += 1
        return _Row(self._pairs.pop(0))


def test_stage_queue_depths_maps_every_stage_and_computes_age() -> None:
    now = datetime.now(timezone.utc)
    pairs = [
        (0, None),  # relevance_filter
        (0, None),  # pre_extraction_dedup
        (0, None),  # tier1_extraction
        (3, now - timedelta(seconds=3600)),  # matching
        (0, None),  # fast_path
        (0, None),  # tier2_detail_fill
        (0, None),  # embedding
        (0, None),  # materialization
    ]
    service = PipelineHealthService(_StubSession(pairs))  # type: ignore[arg-type]

    depths = service.stage_queue_depths()

    assert [d.stage_name for d in depths] == _STAGE_ORDER
    by_name = {d.stage_name: d for d in depths}
    assert by_name["matching"].queue_depth == 3
    assert 3590 < by_name["matching"].oldest_waiting_seconds < 3610
    assert by_name["relevance_filter"].queue_depth == 0
    assert by_name["relevance_filter"].oldest_waiting_seconds is None


def test_age_seconds_never_negative_for_future_timestamp() -> None:
    now = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
    future = now + timedelta(seconds=30)
    assert PipelineHealthService._age_seconds(future, now) == 0.0


def test_age_seconds_treats_naive_timestamp_as_utc() -> None:
    now = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
    naive = datetime(2026, 9, 2, 11, 59, 0)
    assert PipelineHealthService._age_seconds(naive, now) == 60.0
