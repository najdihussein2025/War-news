from __future__ import annotations

from types import SimpleNamespace

from app.news.services.matching.emergency_organization_matching_service import (
    EmergencyOrganizationMatchingService,
)
from app.news.services.matching.matching_service import (
    LOW_CONFIDENCE_THRESHOLD,
    MATCH_THRESHOLD,
)


class _RepoStub:
    def __init__(self, candidates) -> None:
        self.candidates = candidates
        self.calls: list[tuple[str, int]] = []

    def find_similar(self, text: str, limit: int = 5):
        self.calls.append((text, limit))
        return self.candidates

    def list_active(self):  # pragma: no cover - unused here
        return [c for c, _ in self.candidates]


def _org(**kw):
    return SimpleNamespace(
        id=kw.get("id", 1),
        name_ar=kw.get("name_ar", "كشافة الرسالة الإسلامية"),
        name_en=kw.get("name_en", "Islamic Message Scouts"),
        org_type=kw.get("org_type", "scout_paramedic"),
    )


def test_confident_match_returns_canonical_names() -> None:
    repo = _RepoStub([(_org(), 0.82)])
    result = EmergencyOrganizationMatchingService(repo).match("كشافة الرسالة الاسلامية")

    assert result.status == "matched"
    assert result.matched_id == 1
    assert result.matched_name_ar == "كشافة الرسالة الإسلامية"
    assert result.matched_name_en == "Islamic Message Scouts"
    assert result.review_required is False
    assert result.confidence == 0.82


def test_low_confidence_is_flagged() -> None:
    repo = _RepoStub([(_org(), 0.45)])
    result = EmergencyOrganizationMatchingService(repo).match("كشافة")

    assert result.status == "matched_low_confidence"
    assert result.matched_id == 1
    assert result.review_required is True


def test_below_low_threshold_is_unmatched_but_keeps_score() -> None:
    repo = _RepoStub([(_org(), 0.20)])
    result = EmergencyOrganizationMatchingService(repo).match("جيش")

    assert result.status == "unmatched"
    assert result.matched_id is None
    assert result.confidence == 0.20


def test_empty_text_is_unmatched() -> None:
    repo = _RepoStub([(_org(), 0.99)])
    result = EmergencyOrganizationMatchingService(repo).match("   ")
    assert result.status == "unmatched"
    assert repo.calls == []


def test_no_candidates_is_unmatched() -> None:
    repo = _RepoStub([])
    result = EmergencyOrganizationMatchingService(repo).match("مسعفون")
    assert result.status == "unmatched"


def test_tier_boundaries_match_the_shared_matching_service_constants() -> None:
    assert MATCH_THRESHOLD == 0.6
    assert LOW_CONFIDENCE_THRESHOLD == 0.35

    repo_at_match = _RepoStub([(_org(), MATCH_THRESHOLD)])
    assert (
        EmergencyOrganizationMatchingService(repo_at_match).match("x").status
        == "matched"
    )
    repo_at_low = _RepoStub([(_org(), LOW_CONFIDENCE_THRESHOLD)])
    assert (
        EmergencyOrganizationMatchingService(repo_at_low).match("x").status
        == "matched_low_confidence"
    )
