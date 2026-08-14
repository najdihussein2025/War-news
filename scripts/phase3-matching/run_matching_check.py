from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import SessionLocal
from app.api.factories.action_factory import build_match_incident_action
from app.news.models import (
    Condition,
    MessageStatus,
    RawMessage,
    Village,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Match extracted villages and conditions for parsed messages."
    )
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument(
        "--rematch",
        action="store_true",
        help="Include messages that already have a match_result.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.limit < 1:
        raise SystemExit("--limit must be at least 1")

    db = SessionLocal()
    try:
        query = (
            select(RawMessage.id)
            .where(
                RawMessage.status == MessageStatus.parsed,
                RawMessage.extraction_result.is_not(None),
            )
            .order_by(RawMessage.id.asc())
            .limit(args.limit)
        )
        if not args.rematch:
            query = query.where(RawMessage.match_result.is_(None))

        raw_message_ids = list(db.scalars(query).all())
        action = build_match_incident_action(db)
        for raw_message_id in raw_message_ids:
            message = db.get(RawMessage, raw_message_id)
            try:
                result = action.execute(raw_message_id)
                village = (
                    db.get(Village, result.matched_village_id)
                    if result.matched_village_id is not None
                    else None
                )
                condition = (
                    db.get(Condition, result.matched_condition_id)
                    if result.matched_condition_id is not None
                    else None
                )
                output = {
                    "raw_message_id": raw_message_id,
                    "raw_text": message.raw_text if message else None,
                    "village": {
                        "name": village.acs_name if village else None,
                        "confidence": result.village_confidence,
                        "status": result.village_match_status.value,
                    },
                    "condition": {
                        "name": condition.action_ar if condition else None,
                        "confidence": result.condition_confidence,
                        "status": result.condition_match_status.value,
                    },
                }
            except Exception as exc:
                db.rollback()
                output = {
                    "raw_message_id": raw_message_id,
                    "raw_text": message.raw_text if message else None,
                    "error": str(exc),
                }
            print(json.dumps(output, ensure_ascii=False, indent=2))

        print(f"processed={len(raw_message_ids)}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
