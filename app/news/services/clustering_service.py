from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from math import sqrt
from typing import Any

from sqlalchemy import Integer, and_, cast, or_, select, type_coerce
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.core.config import settings
from app.news.models import MessageStatus, RawMessage, TrustTier
from app.news.repositories.channel_trust_tier_repository import (
    ChannelTrustTierRepository,
)

logger = logging.getLogger(__name__)

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


def village_ids_from_match_result(
    match_result: dict[str, Any] | None,
) -> frozenset[int]:
    """Return all matched village IDs from either the old flat or new list shape."""
    if not match_result:
        return frozenset()

    # New shape: village_matches list of dicts
    village_matches = match_result.get("village_matches")
    if isinstance(village_matches, list):
        ids: set[int] = set()
        for vm in village_matches:
            if not isinstance(vm, dict):
                continue
            vid = vm.get("matched_village_id")
            if isinstance(vid, int) and not isinstance(vid, bool):
                ids.add(vid)
        return frozenset(ids)

    # Old flat shape: matched_village_id at top level
    vid = match_result.get("matched_village_id")
    if isinstance(vid, bool):
        return frozenset()
    if isinstance(vid, int):
        return frozenset({vid})
    return frozenset()


def village_id_from_match_result(
    match_result: dict[str, Any] | None,
) -> int | None:
    """Return a single village ID — the smallest one — for backward-compat callers."""
    ids = village_ids_from_match_result(match_result)
    if not ids:
        return None
    return min(ids)


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

    def _effective_row_cap(self, max_rows: int | None) -> int:
        """Never exceed settings.clustering_max_rows_per_pass in one pass."""
        service_cap = max(1, settings.clustering_max_rows_per_pass)
        if max_rows is None:
            return service_cap
        return max(1, min(max_rows, service_cap))

    def load_eligible_messages(self, *, max_rows: int | None = None) -> list[RawMessage]:
        row_cap = self._effective_row_cap(max_rows)
        messages = list(
            self.db.scalars(
                select(RawMessage)
                .where(
                    RawMessage.status == MessageStatus.parsed,
                    RawMessage.content_embedding.is_not(None),
                    RawMessage.match_result.is_not(None),
                    RawMessage.duplicate_of_id.is_(None),
                )
                .order_by(RawMessage.id.asc())
                .limit(row_cap)
            ).all()
        )
        if len(messages) >= row_cap:
            logger.info(
                "Clustering loaded %s eligible rows (cap=%s); remainder waits for next pass",
                len(messages),
                row_cap,
            )
        return messages

    def cluster_eligible(self, *, max_rows: int | None = None) -> list[list[RawMessage]]:
        messages = self.load_eligible_messages(max_rows=max_rows)
        return self.cluster_batch(messages)

    def find_candidates(self, raw_message: RawMessage) -> list[RawMessage]:
        village_ids = village_ids_from_match_result(raw_message.match_result)
        if not village_ids or raw_message.message_datetime is None:
            return []

        # Use the smallest village_id for the index-friendly SQL filter.
        # A secondary in-memory filter via _are_candidates handles messages that
        # only overlap on other village IDs.
        village_id = min(village_ids)

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
                        or_(
                            # Old flat shape
                            cast(
                                RawMessage.match_result["matched_village_id"].astext,
                                Integer,
                            )
                            == village_id,
                            # New list shape — containment check
                            RawMessage.match_result.op("@>")(
                                type_coerce(
                                    {
                                        "village_matches": [
                                            {"matched_village_id": village_id}
                                        ]
                                    },
                                    JSONB,
                                )
                            ),
                        ),
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
        left_ids = village_ids_from_match_result(left.match_result)
        right_ids = village_ids_from_match_result(right.match_result)
        # At least one village ID must be shared between the two messages.
        if not left_ids or not right_ids or not (left_ids & right_ids):
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
