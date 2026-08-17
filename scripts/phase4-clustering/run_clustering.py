from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401
from app.core.database import SessionLocal
from app.llm.dtos import ExtractPendingMessagesData
from app.news.models import MessageStatus, RawMessage
from app.news.repositories.channel_trust_tier_repository import (
    ChannelTrustTierRepository,
)
from app.news.repositories.raw_message_repository import RawMessageRepository
from app.news.services.clustering_service import ClusteringService

DEFAULT_BATCH_SIZE = ExtractPendingMessagesData().batch_size

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cluster parsed raw messages and mark duplicates."
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="Number of raw messages to load per batch.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be at least 1")

    processed = 0
    clusters_formed = 0
    duplicates_marked = 0
    singleton_count = 0
    failed_cluster_representatives: list[int | None] = []
    last_seen_id = 0

    db = SessionLocal()
    repository = RawMessageRepository(db)
    service = ClusteringService(
        db=db,
        channel_trust_tiers=ChannelTrustTierRepository(db),
    )

    try:
        while True:
            batch = list(
                db.scalars(
                    select(RawMessage)
                    .where(
                        RawMessage.id > last_seen_id,
                        RawMessage.status == MessageStatus.parsed,
                        RawMessage.content_embedding.is_not(None),
                        RawMessage.match_result.is_not(None),
                        RawMessage.duplicate_of_id.is_(None),
                    )
                    .order_by(RawMessage.id.asc())
                    .limit(args.batch_size)
                ).all()
            )
            if not batch:
                break

            last_seen_id = batch[-1].id
            processed += len(batch)
            batch_clusters = 0
            batch_duplicates = 0
            batch_singletons = 0
            batch_failures = 0

            for cluster in service.cluster_batch(batch):
                if len(cluster) == 1:
                    singleton_count += 1
                    batch_singletons += 1
                    continue

                clusters_formed += 1
                batch_clusters += 1
                representative_id: int | None = None
                try:
                    representative = service.pick_representative(cluster)
                    representative_id = representative.id
                    member_ids = [
                        message.id
                        for message in cluster
                        if message.id != representative_id
                    ]
                    repository.mark_cluster_duplicates(
                        representative_id=representative_id,
                        member_ids=member_ids,
                    )
                    duplicates_marked += len(member_ids)
                    batch_duplicates += len(member_ids)
                    logger.info(
                        "Cluster formed representative_id=%s member_ids=%s "
                        "member_count=%s",
                        representative_id,
                        member_ids,
                        len(cluster),
                    )
                except Exception as exc:
                    repository.rollback()
                    error_message = str(exc) or f"{type(exc).__name__}: {exc}"
                    failed_cluster_representatives.append(representative_id)
                    batch_failures += 1
                    logger.error(
                        "Cluster failed representative_id=%s error=%s",
                        representative_id,
                        error_message,
                    )

            logger.info(
                "Batch processed=%s clusters=%s duplicates=%s "
                "singletons=%s failed_clusters=%s",
                len(batch),
                batch_clusters,
                batch_duplicates,
                batch_singletons,
                batch_failures,
            )
    finally:
        db.close()

    failed_ids = [
        str(representative_id) if representative_id is not None else "unknown"
        for representative_id in failed_cluster_representatives
    ]
    print(
        f"processed={processed} clusters_formed={clusters_formed} "
        f"duplicates_marked={duplicates_marked} singletons={singleton_count} "
        f"failed_clusters={len(failed_cluster_representatives)} "
        f"failed_representative_ids={failed_ids}"
    )


if __name__ == "__main__":
    main()
