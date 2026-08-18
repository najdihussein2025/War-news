from __future__ import annotations

import logging
import sys
from pathlib import Path

from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401
from app.core.database import SessionLocal
from app.news.models import RawMessage
from app.news.services.clustering_service import ClusteringService
from app.news.services.pipeline_sweep_stages import (
    cluster_all_eligible,
    sweep_clustering,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def _cluster_all_eligible(
    db: Session,
    service: ClusteringService,
) -> list[list[RawMessage]]:
    return cluster_all_eligible(db, service)


def main() -> None:
    db = SessionLocal()
    try:
        result = sweep_clustering(db)
        print(
            f"processed={result.processed} succeeded={result.succeeded} "
            f"failed={result.failed}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
