from __future__ import annotations

import logging
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401
from app.core.database import SessionLocal
from app.news.models import MessageStatus, RawMessage
from app.news.repositories.channel_trust_tier_repository import (
    ChannelTrustTierRepository,
)
from app.news.repositories.incident_repository import IncidentRepository
from app.news.repositories.raw_message_repository import RawMessageRepository
from app.news.services.clustering_service import ClusteringService

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def _cluster_all_eligible(
    db: Session,
    service: ClusteringService,
) -> list[list[RawMessage]]:
    messages = list(
        db.scalars(
            select(RawMessage)
            .where(
                RawMessage.status == MessageStatus.parsed,
                RawMessage.content_embedding.is_not(None),
                RawMessage.match_result.is_not(None),
                RawMessage.duplicate_of_id.is_(None),
            )
            .order_by(RawMessage.id.asc())
        ).all()
    )
    return service.cluster_batch(messages)


def main() -> None:
    processed = 0
    clusters_formed = 0
    duplicates_marked = 0
    incidents_soft_deleted = 0
    singleton_count = 0
    failed_cluster_representatives: list[int | None] = []

    db = SessionLocal()
    repository = RawMessageRepository(db)
    incident_repository = IncidentRepository(db)
    service = ClusteringService(
        db=db,
        channel_trust_tiers=ChannelTrustTierRepository(db),
    )

    try:
        clusters = _cluster_all_eligible(db, service)
        processed = sum(len(cluster) for cluster in clusters)

        for cluster in clusters:
            if len(cluster) == 1:
                singleton_count += 1
                continue

            clusters_formed += 1
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
                    commit=False,
                )
                deleted_incident_ids = [
                    incident_id
                    for member_id in member_ids
                    for incident_id in incident_repository.soft_delete_for_raw_message_id(
                        member_id
                    )
                ]
                db.commit()
                duplicates_marked += len(member_ids)
                incidents_soft_deleted += len(deleted_incident_ids)
                logger.info(
                    "Cluster formed representative_id=%s member_ids=%s "
                    "member_count=%s soft_deleted_incident_ids=%s",
                    representative_id,
                    member_ids,
                    len(cluster),
                    deleted_incident_ids,
                )
            except Exception as exc:
                repository.rollback()
                error_message = str(exc) or f"{type(exc).__name__}: {exc}"
                failed_cluster_representatives.append(representative_id)
                logger.error(
                    "Cluster failed representative_id=%s error=%s",
                    representative_id,
                    error_message,
                )

        logger.info(
            "Eligible dataset processed=%s clusters=%s duplicates=%s "
            "singletons=%s failed_clusters=%s",
            processed,
            clusters_formed,
            duplicates_marked,
            singleton_count,
            len(failed_cluster_representatives),
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
        f"incidents_soft_deleted={incidents_soft_deleted} "
        f"failed_clusters={len(failed_cluster_representatives)} "
        f"failed_representative_ids={failed_ids}"
    )


if __name__ == "__main__":
    main()
