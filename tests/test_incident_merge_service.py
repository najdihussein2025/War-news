from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.news.services.dedup.dedup_matching_service import DedupMatchingService
from app.news.services.dedup.incident_merge_service import IncidentMergeService


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


def test_canonicalize_existing_merges_then_retires_duplicate() -> None:
    repo = MagicMock()
    service = IncidentMergeService(repo)
    canonical = SimpleNamespace(id="canonical")
    duplicate = SimpleNamespace(
        id="duplicate",
        raw_message_id=22,
        village_id=7,
    )
    data = {"injuries": 2}

    service.canonicalize_existing(
        canonical=canonical,
        duplicate=duplicate,
        new_candidate_data=data,
        similarity_score=0.81,
    )

    repo.merge_existing.assert_called_once_with(
        existing=canonical,
        new_candidate_data=data,
        raw_message_id=22,
    )
    repo.soft_delete_for_village_incident.assert_called_once_with(
        22,
        7,
        matched_incident_id="canonical",
        similarity_score=0.81,
    )
