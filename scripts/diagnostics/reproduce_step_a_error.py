from __future__ import annotations

import asyncio
import sys
import traceback
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import SessionLocal
from app.core.news_action_factory import build_relevance_classifier
from app.models.news import MessageStatus, RawMessage


PREFERRED_RAW_MESSAGE_ID = 691464
ADDITIONAL_SUCCESS_ROWS = 3


async def classify_one(classifier, message: RawMessage) -> bool:
    print(f"=== raw_message id={message.id} external_message_id={message.external_message_id!r} ===")
    try:
        results = await classifier.classify_batch([message])
        if len(results) != 1:
            raise RuntimeError(
                f"Classifier returned {len(results)} results for one message."
            )
        result = results[0]
        print("result: success")
        print(f"verdict: {result.verdict.value}")
        print(f"classification: {result.model_dump_json()}")
        return True
    except Exception as exc:
        print("result: exception")
        print(f"exception_type: {type(exc).__name__}")
        print(f"exception_message: {str(exc)!r}")
        print("traceback:")
        print(traceback.format_exc(), end="")
        return False
    finally:
        print()


async def main() -> None:
    db = SessionLocal()
    try:
        preferred = db.scalar(
            select(RawMessage).where(
                RawMessage.id == PREFERRED_RAW_MESSAGE_ID,
                RawMessage.status == MessageStatus.error,
            )
        )
        if preferred is None:
            preferred = db.scalar(
                select(RawMessage)
                .where(RawMessage.status == MessageStatus.error)
                .order_by(RawMessage.id.desc())
                .limit(1)
            )
        if preferred is None:
            raise RuntimeError("No raw_messages row with status='error' was found.")

        classifier = build_relevance_classifier()
        attempted_ids = [preferred.id]
        first_succeeded = await classify_one(classifier, preferred)

        if first_succeeded:
            additional = list(
                db.scalars(
                    select(RawMessage)
                    .where(
                        RawMessage.status == MessageStatus.error,
                        RawMessage.id != preferred.id,
                    )
                    .order_by(RawMessage.id.desc())
                    .limit(ADDITIONAL_SUCCESS_ROWS)
                )
            )
            for message in additional:
                attempted_ids.append(message.id)
                await classify_one(classifier, message)

        print("attempted_ids: " + ", ".join(str(value) for value in attempted_ids))
    finally:
        # This diagnostic intentionally persists nothing, even if future edits
        # accidentally mutate an ORM object during classification.
        db.rollback()
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
