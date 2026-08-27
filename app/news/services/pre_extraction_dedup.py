from __future__ import annotations

import logging

from sqlalchemy import func, literal, select, text
from sqlalchemy.orm import Session

from app.news.models import MessageStatus, RawMessage

logger = logging.getLogger(__name__)


def choose_pre_dedup_original_id(
    candidate_id: int,
    match_id: int,
) -> int | None:
    """
    Return the canonical original id when candidate should be marked duplicate.

    The lower raw_message id is always the original; the higher id is the duplicate.
    When candidate_id is already the lower id, return None (do not mark it duplicate).
    """
    original_id = min(candidate_id, match_id)
    if candidate_id == original_id:
        return None
    return original_id


def is_valid_pre_dedup_original(
    db: Session,
    *,
    candidate_id: int,
    original_id: int,
) -> bool:
    """Reject targets that would create a 2-cycle or point at a non-original row."""
    if original_id == candidate_id:
        return False

    original = db.get(RawMessage, original_id)
    if original is None:
        return False

    if original.status == MessageStatus.duplicate:
        return False

    if original.duplicate_of_id == candidate_id:
        return False

    return True


def find_pre_dedup_match(
    db: Session,
    *,
    raw_message_id: int,
    raw_text: str,
    threshold: float,
):
    score_col = func.word_similarity(
        RawMessage.raw_text,
        literal(raw_text),
    ).label("score")
    return db.execute(
        select(RawMessage.id, score_col)
        .where(
            RawMessage.status.not_in(
                [
                    MessageStatus.rejected,
                    MessageStatus.duplicate,
                    MessageStatus.materialized,
                ]
            ),
            RawMessage.received_at >= func.now() - text("INTERVAL '48 hours'"),
            RawMessage.id != raw_message_id,
            RawMessage.raw_text.is_not(None),
        )
        .order_by(score_col.desc(), RawMessage.id.asc())
        .limit(1)
    ).first()


def process_pre_dedup_message(
    db: Session,
    *,
    raw_message_id: int,
    threshold: float,
) -> bool:
    """
    Evaluate one message for pre-extraction dedup.

    Returns True when the message was marked duplicate.
    """
    msg = db.get(RawMessage, raw_message_id)
    if msg is None:
        raise ValueError(f"RawMessage id={raw_message_id} not found")
    if msg.raw_text is None:
        return False

    best = find_pre_dedup_match(
        db,
        raw_message_id=raw_message_id,
        raw_text=msg.raw_text,
        threshold=threshold,
    )
    if best is None or best.score < threshold:
        return False

    original_id = choose_pre_dedup_original_id(raw_message_id, best.id)
    if original_id is None:
        return False

    if not is_valid_pre_dedup_original(
        db,
        candidate_id=raw_message_id,
        original_id=original_id,
    ):
        logger.info(
            "pre_extraction_dedup raw_message_id=%s skipped match "
            "raw_message_id=%s: invalid original target",
            raw_message_id,
            original_id,
        )
        return False

    msg.status = MessageStatus.duplicate
    msg.duplicate_of_id = original_id
    db.commit()
    logger.info(
        "pre_extraction_dedup raw_message_id=%s: word_similarity=%.3f"
        " similar_to_raw_message_id=%s",
        raw_message_id,
        best.score,
        original_id,
    )
    return True
