from __future__ import annotations

from sqlalchemy import func, literal, select, text
from sqlalchemy.orm import Session

from app.news.models import MessageStatus, RawMessage


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
                [MessageStatus.rejected, MessageStatus.duplicate]
            ),
            RawMessage.received_at >= func.now() - text("INTERVAL '48 hours'"),
            RawMessage.id != raw_message_id,
            RawMessage.raw_text.is_not(None),
        )
        .order_by(score_col.desc(), RawMessage.id.asc())
        .limit(1)
    ).first()
