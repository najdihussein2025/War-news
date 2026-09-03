from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.core.config import settings
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


class _CursorStubSession:
    def __init__(self, *, cursor, max_id, relevance_backlog: int = 0) -> None:
        self._cursor = cursor
        self._max_id = max_id
        self._relevance_backlog = relevance_backlog

    def get(self, _model, _pk):
        return self._cursor

    def execute(self, _stmt):
        # First call: MAX(id); second: relevance-eligible backlog count.
        if not hasattr(self, "_execute_calls"):
            self._execute_calls = 0
        self._execute_calls += 1
        if self._execute_calls == 1:
            return SimpleNamespace(scalar_one=lambda: self._max_id)
        return SimpleNamespace(scalar_one=lambda: self._relevance_backlog)


def test_cursor_gap_healthy_when_within_thresholds() -> None:
    cursor = SimpleNamespace(
        last_processed_id=2500,
        updated_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    service = PipelineHealthService(
        _CursorStubSession(cursor=cursor, max_id=2550, relevance_backlog=50)  # type: ignore[arg-type]
    )

    gap = service.cursor_gap()

    assert gap.sweep_name == "live_sweep_new_only"
    assert gap.last_processed_id == 2500
    assert gap.max_raw_message_id == 2550
    assert gap.gap == 50
    assert gap.unhealthy is False


def test_cursor_gap_unhealthy_when_row_gap_exceeds_threshold() -> None:
    cursor = SimpleNamespace(
        last_processed_id=10,
        updated_at=datetime.now(timezone.utc),
    )
    backlog = settings.pipeline_cursor_gap_row_threshold + 1
    service = PipelineHealthService(
        _CursorStubSession(cursor=cursor, max_id=9999, relevance_backlog=backlog)  # type: ignore[arg-type]
    )

    gap = service.cursor_gap()

    assert gap.gap == settings.pipeline_cursor_gap_row_threshold + 1
    assert gap.unhealthy is True


def test_cursor_gap_unhealthy_when_stalled_with_relevance_backlog() -> None:
    stale_minutes = settings.pipeline_cursor_stale_minutes + 5
    cursor = SimpleNamespace(
        last_processed_id=2500,
        updated_at=datetime.now(timezone.utc) - timedelta(minutes=stale_minutes),
    )
    service = PipelineHealthService(
        _CursorStubSession(cursor=cursor, max_id=2505, relevance_backlog=3)  # type: ignore[arg-type]
    )

    gap = service.cursor_gap()

    assert gap.gap == 3
    assert gap.unhealthy is True


def test_cursor_gap_not_stale_when_preclassified_traffic_only() -> None:
    stale_minutes = settings.pipeline_cursor_stale_minutes + 5
    cursor = SimpleNamespace(
        last_processed_id=2500,
        updated_at=datetime.now(timezone.utc) - timedelta(minutes=stale_minutes),
    )
    # Large ID gap but zero relevance-eligible backlog (CNRS-style traffic).
    service = PipelineHealthService(
        _CursorStubSession(cursor=cursor, max_id=3500, relevance_backlog=0)  # type: ignore[arg-type]
    )

    gap = service.cursor_gap()

    assert gap.gap == 0
    assert gap.unhealthy is False


def test_cursor_gap_not_stale_flagged_when_no_newer_rows() -> None:
    cursor = SimpleNamespace(
        last_processed_id=2500,
        updated_at=datetime.now(timezone.utc) - timedelta(days=2),
    )
    service = PipelineHealthService(
        _CursorStubSession(cursor=cursor, max_id=2500)  # type: ignore[arg-type]
    )

    gap = service.cursor_gap()

    assert gap.gap == 0
    assert gap.unhealthy is False


def test_cursor_gap_handles_missing_cursor_row() -> None:
    service = PipelineHealthService(
        _CursorStubSession(cursor=None, max_id=42, relevance_backlog=0)  # type: ignore[arg-type]
    )

    gap = service.cursor_gap()

    assert gap.last_processed_id == 0
    assert gap.gap == 0
    assert gap.unhealthy is False


def test_latency_summary_maps_both_cohorts_and_omits_slo_target() -> None:
    pairs = [
        (120.0, 300.0, 480.0, 42),  # materialized
        (None, None, None, 0),  # terminal_non_materialized (no rows)
    ]
    service = PipelineHealthService(_StubSession(pairs))  # type: ignore[arg-type]

    summary = service.latency_summary()

    assert summary.window_hours == 24
    assert summary.materialized.p50_seconds == 120.0
    assert summary.materialized.p95_seconds == 300.0
    assert summary.materialized.p99_seconds == 480.0
    assert summary.materialized.sample_size == 42
    assert summary.terminal_non_materialized.sample_size == 0
    assert summary.terminal_non_materialized.p50_seconds is None
    # No pass/fail SLO field anywhere on the summary.
    assert not hasattr(summary, "slo_met")
    assert not hasattr(summary.materialized, "slo_met")
