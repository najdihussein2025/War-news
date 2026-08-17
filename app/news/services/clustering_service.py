from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import sqrt
from typing import Any

from sqlalchemy import Integer, and_, cast, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.news.models import MessageStatus, RawMessage, TrustTier
from app.news.repositories.channel_trust_tier_repository import (
    ChannelTrustTierRepository,
)

TRUST_TIER_RANK = {
    TrustTier.official: 0,
    TrustTier.trusted: 1,
    TrustTier.detail: 2,
}
UNKNOWN_TRUST_TIER_RANK = len(TRUST_TIER_RANK)
MATCHED_CONDITION_STATUSES = frozenset({"matched", "matched_low_confidence"})


def cosine_similarity(
    left: list[float] | None,
    right: list[float] | None,
) -> float:
    if left is None or right is None:
        return 0.0
    if len(left) != len(right) or not left:
        return 0.0

    dot_product = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for left_value, right_value in zip(left, right, strict=True):
        dot_product += left_value * right_value
        left_norm += left_value * left_value
        right_norm += right_value * right_value

    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot_product / (sqrt(left_norm) * sqrt(right_norm))


def match_result_value(
    match_result: dict[str, Any] | None,
    key: str,
) -> Any:
    if not match_result:
        return None
    return match_result.get(key)


def village_id_from_match_result(
    match_result: dict[str, Any] | None,
) -> int | None:
    village_id = match_result_value(match_result, "matched_village_id")
    if isinstance(village_id, bool):
        return None
    if isinstance(village_id, int):
        return village_id
    return None


def conditions_allow_merge(
    left: dict[str, Any] | None,
    right: dict[str, Any] | None,
) -> bool:
    left_status = match_result_value(left, "condition_match_status")
    right_status = match_result_value(right, "condition_match_status")
    if left_status not in MATCHED_CONDITION_STATUSES:
        return False
    if right_status not in MATCHED_CONDITION_STATUSES:
        return False

    left_condition_id = match_result_value(left, "matched_condition_id")
    right_condition_id = match_result_value(right, "matched_condition_id")
    if isinstance(left_condition_id, bool) or isinstance(right_condition_id, bool):
        return False
    if not isinstance(left_condition_id, int) or not isinstance(right_condition_id, int):
        return False
    return left_condition_id == right_condition_id


class ClusteringService:
    def __init__(
        self,
        db: Session,
        channel_trust_tiers: ChannelTrustTierRepository,
        time_window_minutes: int | None = None,
        similarity_threshold: float | None = None,
        require_condition_match: bool | None = None,
    ) -> None:
        self.db = db
        self.channel_trust_tiers = channel_trust_tiers
        self.time_window_minutes = (
            time_window_minutes
            if time_window_minutes is not None
            else settings.cluster_time_window_minutes
        )
        self.similarity_threshold = (
            similarity_threshold
            if similarity_threshold is not None
            else settings.cluster_similarity_threshold
        )
        self.require_condition_match = (
            require_condition_match
            if require_condition_match is not None
            else settings.cluster_require_condition_match
        )

    def find_candidates(self, raw_message: RawMessage) -> list[RawMessage]:
        village_id = village_id_from_match_result(raw_message.match_result)
        if village_id is None or raw_message.message_datetime is None:
            return []

        window = timedelta(minutes=self.time_window_minutes)
        start = raw_message.message_datetime - window
        end = raw_message.message_datetime + window

        return list(
            self.db.scalars(
                select(RawMessage)
                .where(
                    and_(
                        RawMessage.status == MessageStatus.parsed,
                        RawMessage.id != raw_message.id,
                        RawMessage.content_embedding.is_not(None),
                        RawMessage.message_datetime >= start,
                        RawMessage.message_datetime <= end,
                        cast(
                            RawMessage.match_result["matched_village_id"].astext,
                            Integer,
                        )
                        == village_id,
                    )
                )
                .order_by(RawMessage.message_datetime.asc(), RawMessage.id.asc())
            ).all()
        )

    def should_merge(self, left: RawMessage, right: RawMessage) -> bool:
        similarity = cosine_similarity(
            left.content_embedding,
            right.content_embedding,
        )
        if similarity < self.similarity_threshold:
            return False

        if not self.require_condition_match:
            return True

        return conditions_allow_merge(left.match_result, right.match_result)

    def pick_representative(self, cluster: list[RawMessage]) -> RawMessage:
        if not cluster:
            raise ValueError("cluster must contain at least one message")

        return min(
            cluster,
            key=lambda message: (
                self._trust_rank(message),
                message.message_datetime
                or datetime.max.replace(tzinfo=timezone.utc),
                message.id,
            ),
        )

    def cluster_batch(self, messages: list[RawMessage]) -> list[list[RawMessage]]:
        if not messages:
            return []

        parent = {message.id: message.id for message in messages}

        def find(message_id: int) -> int:
            root = message_id
            while parent[root] != root:
                parent[root] = parent[parent[root]]
                root = parent[root]
            return root

        def union(left_id: int, right_id: int) -> None:
            left_root = find(left_id)
            right_root = find(right_id)
            if left_root != right_root:
                parent[right_root] = left_root

        for index, left in enumerate(messages):
            for right in messages[index + 1 :]:
                if self._are_candidates(left, right) and self.should_merge(left, right):
                    union(left.id, right.id)

        grouped: dict[int, list[RawMessage]] = {}
        for message in messages:
            grouped.setdefault(find(message.id), []).append(message)

        return list(grouped.values())

    def _are_candidates(self, left: RawMessage, right: RawMessage) -> bool:
        left_village_id = village_id_from_match_result(left.match_result)
        right_village_id = village_id_from_match_result(right.match_result)
        if left_village_id is None or left_village_id != right_village_id:
            return False

        if left.message_datetime is None or right.message_datetime is None:
            return False

        window = timedelta(minutes=self.time_window_minutes)
        return abs(left.message_datetime - right.message_datetime) <= window

    def _trust_rank(self, message: RawMessage) -> int:
        channel_name = message.source_name
        if not channel_name:
            return UNKNOWN_TRUST_TIER_RANK

        tier_row = self.channel_trust_tiers.get_tier_by_channel_name(channel_name)
        if tier_row is None:
            return UNKNOWN_TRUST_TIER_RANK

        return TRUST_TIER_RANK[tier_row.tier]
