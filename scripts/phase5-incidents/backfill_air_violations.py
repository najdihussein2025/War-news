from __future__ import annotations

import logging
import sys
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401
from app.core.database import SessionLocal
from app.news.dtos import MatchResultDTO
from app.news.models import AirViolation, RawMessage
from app.news.repositories.air_violation_repository import AirViolationRepository

RAW_MESSAGE_IDS = (
    691438,
    691439,
    691442,
    691444,
    691450,
    692014,
    692015,
    692018,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    db = SessionLocal()
    repository = AirViolationRepository(db)
    created: list[tuple[int, int]] = []
    skipped: list[int] = []

    try:
        for raw_message_id in RAW_MESSAGE_IDS:
            existing_id = db.scalar(
                select(AirViolation.id).where(
                    AirViolation.raw_message_id == raw_message_id
                )
            )
            if existing_id is not None:
                skipped.append(raw_message_id)
                logger.info(
                    "raw_message_id=%s already has air_violation id=%s, skipping",
                    raw_message_id,
                    existing_id,
                )
                continue

            message = db.get(RawMessage, raw_message_id)
            if message is None:
                raise LookupError(f"raw_message id={raw_message_id} was not found")
            if message.match_result is None:
                raise ValueError(
                    f"raw_message id={raw_message_id} has no match_result"
                )

            try:
                result = MatchResultDTO.model_validate(message.match_result)
            except ValidationError as exc:
                raise ValueError(
                    f"raw_message id={raw_message_id} has invalid match_result"
                ) from exc

            before_count = db.scalar(select(AirViolation.id).where(
                AirViolation.raw_message_id == raw_message_id
            ))
            repository.route_from_match(message, result)
            air_violation_id = db.scalar(
                select(AirViolation.id).where(
                    AirViolation.raw_message_id == raw_message_id
                )
            )
            if air_violation_id is None:
                raise RuntimeError(
                    f"route_from_match did not create air_violation for "
                    f"raw_message_id={raw_message_id} "
                    f"(condition_id={result.matched_condition_id}, "
                    f"village_matches={result.village_matches!r})"
                )
            if before_count is not None:
                raise RuntimeError(
                    f"duplicate air_violation would have been created for "
                    f"raw_message_id={raw_message_id}"
                )

            created.append((air_violation_id, raw_message_id))
            logger.info(
                "Created air_violation id=%s raw_message_id=%s condition_id=%s",
                air_violation_id,
                raw_message_id,
                result.matched_condition_id,
            )

        print(
            f"air_violations_created={len(created)} skipped_existing={len(skipped)} "
            f"rows={created}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
