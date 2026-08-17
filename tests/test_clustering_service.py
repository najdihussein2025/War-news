from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.news.models import TrustTier
from app.news.services.clustering_service import ClusteringService

AIR_STRIKE_CONDITION_ID = 22
ARTILLERY_CONDITION_ID = 5
DEFAULT_VILLAGE_ID = 976


def _embedding(*, primary: float, secondary: float = 0.0) -> list[float]:
    return [primary, secondary, 0.0]


def _match_result(
    *,
    matched_village_id: int | None = DEFAULT_VILLAGE_ID,
    village_match_status: str = "matched",
    village_review_required: bool = False,
    matched_condition_id: int | None = AIR_STRIKE_CONDITION_ID,
    condition_match_status: str = "matched",
    condition_review_required: bool = False,
) -> dict:
    return {
        "raw_village_text": "بنت جبيل",
        "matched_village_id": matched_village_id,
        "raw_condition_text": "غارة جوية",
        "village_confidence": 0.9,
        "condition_confidence": 0.9,
        "matched_condition_id": matched_condition_id,
        "village_match_status": village_match_status,
        "condition_match_status": condition_match_status,
        "village_review_required": village_review_required,
        "condition_review_required": condition_review_required,
    }


def _message(
    *,
    message_id: int,
    source_name: str = "detail_channel",
    message_datetime: datetime | None = None,
    embedding: list[float] | None = None,
    match_result: dict | None = None,
):
    return SimpleNamespace(
        id=message_id,
        source_name=source_name,
        message_datetime=message_datetime
        or datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc),
        content_embedding=embedding,
        match_result=match_result,
    )


class _TrustTierRepositoryStub:
    def __init__(self, tiers: dict[str, TrustTier]) -> None:
        self.tiers = tiers

    def get_tier_by_channel_name(self, channel_name: str):
        tier = self.tiers.get(channel_name)
        if tier is None:
            return None
        return SimpleNamespace(tier=tier)


def _service(
    *,
    similarity_threshold: float = 0.90,
    require_condition_match: bool = True,
    tiers: dict[str, TrustTier] | None = None,
) -> ClusteringService:
    return ClusteringService(
        db=SimpleNamespace(),
        channel_trust_tiers=_TrustTierRepositoryStub(tiers or {}),
        time_window_minutes=90,
        similarity_threshold=similarity_threshold,
        require_condition_match=require_condition_match,
    )


def test_should_merge_combines_similar_messages_in_same_village() -> None:
    service = _service()
    left = _message(
        message_id=1,
        embedding=_embedding(primary=1.0),
        match_result=_match_result(matched_condition_id=AIR_STRIKE_CONDITION_ID),
    )
    right = _message(
        message_id=2,
        embedding=_embedding(primary=1.0),
        match_result=_match_result(matched_condition_id=AIR_STRIKE_CONDITION_ID),
    )

    assert service.should_merge(left, right) is True


def test_should_not_merge_same_village_with_different_conditions() -> None:
    service = _service()
    left = _message(
        message_id=1,
        embedding=_embedding(primary=1.0),
        match_result=_match_result(matched_condition_id=ARTILLERY_CONDITION_ID),
    )
    right = _message(
        message_id=2,
        embedding=_embedding(primary=1.0),
        match_result=_match_result(matched_condition_id=AIR_STRIKE_CONDITION_ID),
    )

    assert service.should_merge(left, right) is False


def test_low_confidence_condition_match_does_not_force_merge_without_similarity() -> (
    None
):
    service = _service(similarity_threshold=0.90)
    low_confidence_result = _match_result(
        matched_condition_id=AIR_STRIKE_CONDITION_ID,
        condition_match_status="matched_low_confidence",
        condition_review_required=True,
    )
    left = _message(
        message_id=1,
        embedding=_embedding(primary=1.0, secondary=0.0),
        match_result=low_confidence_result,
    )
    right = _message(
        message_id=2,
        embedding=_embedding(primary=0.0, secondary=1.0),
        match_result=low_confidence_result,
    )

    assert service.should_merge(left, right) is False

    same_condition_high_similarity_left = _message(
        message_id=3,
        embedding=_embedding(primary=1.0),
        match_result=low_confidence_result,
    )
    same_condition_high_similarity_right = _message(
        message_id=4,
        embedding=_embedding(primary=1.0),
        match_result=low_confidence_result,
    )

    assert (
        service.should_merge(
            same_condition_high_similarity_left,
            same_condition_high_similarity_right,
        )
        is True
    )


def test_pick_representative_prefers_highest_trust_tier() -> None:
    service = _service(
        tiers={
            "NNALeb": TrustTier.official,
            "sameralhajali": TrustTier.trusted,
            "Janoubana": TrustTier.detail,
        }
    )
    official = _message(
        message_id=1,
        source_name="NNALeb",
        message_datetime=datetime(2026, 8, 17, 12, 30, tzinfo=timezone.utc),
        embedding=_embedding(primary=1.0),
    )
    trusted = _message(
        message_id=2,
        source_name="sameralhajali",
        message_datetime=datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc),
        embedding=_embedding(primary=1.0),
    )
    detail = _message(
        message_id=3,
        source_name="Janoubana",
        message_datetime=datetime(2026, 8, 17, 11, 0, tzinfo=timezone.utc),
        embedding=_embedding(primary=1.0),
    )

    representative = service.pick_representative([detail, trusted, official])

    assert representative.id == official.id


def test_pick_representative_breaks_ties_by_earliest_timestamp() -> None:
    service = _service(
        tiers={
            "Janoubana": TrustTier.detail,
            "nabatiehchannel": TrustTier.detail,
        }
    )
    earlier = _message(
        message_id=10,
        source_name="Janoubana",
        message_datetime=datetime(2026, 8, 17, 11, 0, tzinfo=timezone.utc),
        embedding=_embedding(primary=1.0),
    )
    later = _message(
        message_id=11,
        source_name="nabatiehchannel",
        message_datetime=datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc),
        embedding=_embedding(primary=1.0),
    )

    representative = service.pick_representative([later, earlier])

    assert representative.id == earlier.id


def test_cluster_batch_groups_transitively_similar_messages() -> None:
    service = _service()
    first = _message(
        message_id=1,
        embedding=_embedding(primary=1.0),
        match_result=_match_result(matched_condition_id=AIR_STRIKE_CONDITION_ID),
    )
    second = _message(
        message_id=2,
        embedding=_embedding(primary=1.0),
        match_result=_match_result(matched_condition_id=AIR_STRIKE_CONDITION_ID),
    )
    different_condition = _message(
        message_id=3,
        embedding=_embedding(primary=1.0),
        match_result=_match_result(matched_condition_id=ARTILLERY_CONDITION_ID),
    )

    clusters = service.cluster_batch([first, second, different_condition])

    assert len(clusters) == 2
    merged_cluster = next(cluster for cluster in clusters if len(cluster) == 2)
    singleton_cluster = next(cluster for cluster in clusters if len(cluster) == 1)
    assert {message.id for message in merged_cluster} == {1, 2}
    assert singleton_cluster[0].id == 3


def test_cluster_batch_does_not_group_messages_from_different_villages() -> None:
    service = _service()
    first = _message(
        message_id=1,
        embedding=_embedding(primary=1.0),
        match_result=_match_result(
            matched_village_id=DEFAULT_VILLAGE_ID,
            matched_condition_id=AIR_STRIKE_CONDITION_ID,
        ),
    )
    second = _message(
        message_id=2,
        embedding=_embedding(primary=1.0),
        match_result=_match_result(
            matched_village_id=DEFAULT_VILLAGE_ID + 1,
            matched_condition_id=AIR_STRIKE_CONDITION_ID,
        ),
    )

    assert service.should_merge(first, second) is True

    clusters = service.cluster_batch([first, second])

    assert len(clusters) == 2
    assert [{message.id for message in cluster} for cluster in clusters] == [
        {1},
        {2},
    ]


def test_should_not_merge_when_condition_is_unmatched() -> None:
    service = _service()
    left = _message(
        message_id=1,
        embedding=_embedding(primary=1.0),
        match_result=_match_result(
            matched_condition_id=AIR_STRIKE_CONDITION_ID,
            condition_match_status="matched",
        ),
    )
    right = _message(
        message_id=2,
        embedding=_embedding(primary=1.0),
        match_result=_match_result(
            matched_condition_id=None,
            condition_match_status="unmatched",
            condition_review_required=True,
        ),
    )

    assert service.should_merge(left, right) is False


def test_pick_representative_rejects_empty_cluster() -> None:
    service = _service()

    with pytest.raises(ValueError, match="cluster must contain at least one message"):
        service.pick_representative([])
