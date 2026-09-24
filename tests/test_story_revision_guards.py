"""3.3 / 3.4: story-revision heuristic must not silently regress counts."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from app.llm.dtos import StoryRelationship, StoryRelationshipClassification
from app.llm.services.story_revision_llm_classifier import parse_story_revision_response
from app.news.repositories.incident_repository import IncidentRepository
from app.news.services.dedup.story_relationship_service import StoryRelationshipService

SPARSE_TEXT = "غارة على عيتا الشعب ووقوع اصابات"
PRIOR_TEXT = "غارة على منزل في عيتا الشعب أدت إلى استشهاد 3 وجرح 5"


def _classify(service: StoryRelationshipService, similarity: float):
    return service.classify(
        current_text=SPARSE_TEXT,
        candidate_text=PRIOR_TEXT,
        candidate_incident_id=uuid4(),
        embedding_similarity=similarity,
    )


def test_sparse_similarity_revision_is_marked_heuristic_only() -> None:
    result = _classify(StoryRelationshipService(), 0.60)

    assert result.relationship == StoryRelationship.revision
    assert result.heuristic_only is True


def test_borderline_band_defers_to_llm_when_configured() -> None:
    llm = MagicMock(
        return_value=StoryRelationshipClassification(relationship=StoryRelationship.unrelated)
    )

    result = _classify(StoryRelationshipService(llm_classify=llm), 0.45)

    llm.assert_called_once()
    assert result.relationship == StoryRelationship.unrelated
    assert result.heuristic_only is False


def test_llm_not_called_outside_borderline_band() -> None:
    llm = MagicMock()

    _classify(StoryRelationshipService(llm_classify=llm), 0.80)
    _classify(StoryRelationshipService(llm_classify=llm), 0.20)

    llm.assert_not_called()


def test_story_revision_llm_response_requires_a_marker() -> None:
    confirmed = parse_story_revision_response(
        '{"relationship_hint":"revision","matched_keywords":["حصيلة أولية"]}'
    )
    unsupported = parse_story_revision_response(
        '{"relationship_hint":"revision","matched_keywords":[]}'
    )

    assert confirmed.relationship == StoryRelationship.revision
    assert unsupported.relationship == StoryRelationship.unrelated


def _revision_repo(*, latest_source_at: datetime, new_at: datetime):
    db = MagicMock()
    db.get.return_value = SimpleNamespace(
        message_datetime=new_at,
        received_at=new_at,
        source_name="CNRS",
        source_platform="api",
        source=None,
    )
    db.scalars.return_value.all.return_value = []
    db.scalar.return_value = latest_source_at
    repo = IncidentRepository(db)
    repo._story_revision_already_applied = MagicMock(return_value=False)
    repo._snapshot_merge_audit = MagicMock(return_value={})
    repo._merge_source_label = MagicMock(return_value="CNRS")
    existing = SimpleNamespace(
        id=uuid4(),
        raw_message_id=1,
        martyrs=None,
        deaths=3,
        injuries=5,
        total_deaths=3,
        total_injuries=5,
        verification_status="auto_processed",
        verification_reason=None,
    )
    return repo, existing


def test_heuristic_revision_that_lowers_counts_is_held_for_review() -> None:
    repo, existing = _revision_repo(
        latest_source_at=datetime(2026, 9, 24, 10, tzinfo=timezone.utc),
        new_at=datetime(2026, 9, 24, 11, tzinfo=timezone.utc),
    )

    applied = repo.apply_story_revision(
        existing,
        {"injuries": 2, "total_injuries": 2},
        raw_message_id=9,
        heuristic_only=True,
    )

    assert applied is False
    assert existing.injuries == 5
    assert existing.verification_status == "needs_verification"
    assert "would lower" in existing.verification_reason


def test_confirmed_revision_may_lower_counts() -> None:
    repo, existing = _revision_repo(
        latest_source_at=datetime(2026, 9, 24, 10, tzinfo=timezone.utc),
        new_at=datetime(2026, 9, 24, 11, tzinfo=timezone.utc),
    )

    assert repo.apply_story_revision(
        existing,
        {"injuries": 2},
        raw_message_id=9,
        heuristic_only=False,
    ) is True
    assert existing.injuries == 2


def test_report_not_newer_than_incident_is_not_a_revision() -> None:
    same_time = datetime(2026, 9, 24, 10, tzinfo=timezone.utc)
    repo, existing = _revision_repo(latest_source_at=same_time, new_at=same_time)

    assert repo.apply_story_revision(existing, {"deaths": 4}, raw_message_id=9) is False
    assert existing.deaths == 3
