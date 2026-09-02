from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import app.api.pipeline_router as pipeline_router_module
from app.api.deps import require_super_admin
from app.core.database import get_db
from app.main import app
from app.news.services.pipeline_health_service import StageQueueDepth


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[require_super_admin] = lambda: SimpleNamespace(id=uuid4())
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_pipeline_health_returns_stage_queue_depths(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Service:
        def __init__(self, _db) -> None:
            pass

        def stage_queue_depths(self):
            return [
                StageQueueDepth("relevance_filter", 0, None),
                StageQueueDepth("matching", 3, 3600.5),
            ]

    monkeypatch.setattr(pipeline_router_module, "PipelineHealthService", _Service)

    response = client.get("/api/pipeline/health")

    assert response.status_code == 200
    assert response.json() == [
        {
            "stage_name": "relevance_filter",
            "queue_depth": 0,
            "oldest_waiting_seconds": None,
        },
        {
            "stage_name": "matching",
            "queue_depth": 3,
            "oldest_waiting_seconds": 3600.5,
        },
    ]


def test_pipeline_health_requires_super_admin() -> None:
    app.dependency_overrides.clear()
    with TestClient(app) as anon_client:
        response = anon_client.get("/api/pipeline/health")
    assert response.status_code in (401, 403)
