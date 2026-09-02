from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.news.services.dedup_matching_service import DedupMatchingService
from app.news.services.incident_merge_service import IncidentMergeService


def test_merge_delegates_to_repository_merge_existing() -> None:
    repo = MagicMock()
    service = IncidentMergeService(repo)
    existing = SimpleNamespace(id="incident-1")
    data = {"deaths": 3}

    service.merge(existing=existing, new_candidate_data=data, raw_message_id=99)

    repo.merge_existing.assert_called_once_with(
        existing=existing, new_candidate_data=data, raw_message_id=99
    )


def test_dedup_service_merge_routes_through_shared_path() -> None:
    repo = MagicMock()
    dedup = DedupMatchingService(repo)
    existing = SimpleNamespace(id="incident-1")
    data = {"injuries": 2}

    dedup.merge_into_incident(existing=existing, new_candidate_data=data, raw_message_id=7)

    repo.merge_existing.assert_called_once_with(
        existing=existing, new_candidate_data=data, raw_message_id=7
    )
    assert isinstance(dedup.merge_service, IncidentMergeService)
