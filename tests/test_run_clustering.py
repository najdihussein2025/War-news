from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace

from app.news.services.clustering_service import ClusteringService


class _ScalarResult:
    def __init__(self, messages: list[SimpleNamespace]) -> None:
        self.messages = messages

    def all(self) -> list[SimpleNamespace]:
        return self.messages


class _SessionStub:
    def __init__(self, messages: list[SimpleNamespace]) -> None:
        self.messages = messages

    def scalars(self, _statement) -> _ScalarResult:
        return _ScalarResult(self.messages)


class _TrustTierRepositoryStub:
    def get_tier_by_channel_name(self, _channel_name: str):
        return None


def _load_run_clustering_module() -> ModuleType:
    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "phase4-clustering"
        / "run_clustering.py"
    )
    spec = importlib.util.spec_from_file_location("run_clustering_script", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _message(message_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=message_id,
        source_name="test-channel",
        message_datetime=datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc),
        content_embedding=[1.0, 0.0, 0.0],
        match_result={
            "matched_village_id": 976,
            "matched_condition_id": 22,
            "condition_match_status": "matched",
        },
    )


def test_runner_clusters_eligible_messages_across_old_batch_boundaries() -> None:
    run_clustering = _load_run_clustering_module()
    messages = [_message(1), _message(10_001)]
    db = _SessionStub(messages)
    service = ClusteringService(
        db=db,  # type: ignore[arg-type]
        channel_trust_tiers=_TrustTierRepositoryStub(),  # type: ignore[arg-type]
        time_window_minutes=90,
        similarity_threshold=0.90,
        require_condition_match=True,
    )

    clusters = run_clustering._cluster_all_eligible(db, service)

    assert len(clusters) == 1
    assert {message.id for message in clusters[0]} == {1, 10_001}
