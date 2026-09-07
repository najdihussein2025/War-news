from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func, literal, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.news.models import MessageStatus, RawMessage

logger = logging.getLogger(__name__)

_PRE_DEDUP_NARROWING_VALUES = frozenset(
    {"none", "same_source", "same_source_time_bucket"}
)


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


def _pre_dedup_narrowing_mode() -> str:
    mode = settings.pre_dedup_candidate_narrowing.strip().lower()
    if mode not in _PRE_DEDUP_NARROWING_VALUES:
        logger.warning(
            "Invalid pre_dedup_candidate_narrowing=%r; falling back to same_source",
            settings.pre_dedup_candidate_narrowing,
        )
        return "same_source"
    return mode


def _apply_pre_dedup_candidate_narrowing(
    stmt,
    *,
    source_id: int,
    received_at,
):
    mode = _pre_dedup_narrowing_mode()
    if mode in {"same_source", "same_source_time_bucket"}:
        stmt = stmt.where(RawMessage.source_id == source_id)
    if mode == "same_source_time_bucket":
        bucket_hours = max(1, settings.pre_dedup_time_bucket_hours)
        stmt = stmt.where(
            RawMessage.received_at
            >= received_at - text(f"INTERVAL '{bucket_hours} hours'"),
            RawMessage.received_at
            <= received_at + text(f"INTERVAL '{bucket_hours} hours'"),
        )
    return stmt


def find_pre_dedup_match(
    db: Session,
    *,
    raw_message_id: int,
    source_id: int,
    received_at,
    raw_text: str,
    threshold: float,
):
    window_hours = max(1, settings.pre_dedup_window_hours)
    score_col = func.word_similarity(
        RawMessage.raw_text,
        literal(raw_text),
    ).label("score")
    stmt = (
        select(RawMessage.id, score_col)
        .where(
            RawMessage.status.not_in(
                [
                    MessageStatus.rejected,
                    MessageStatus.duplicate,
                    MessageStatus.materialized,
                ]
            ),
            RawMessage.received_at
            >= func.now() - text(f"INTERVAL '{window_hours} hours'"),
            RawMessage.id != raw_message_id,
            RawMessage.raw_text.is_not(None),
        )
        .order_by(score_col.desc(), RawMessage.id.asc())
        .limit(1)
    )
    stmt = _apply_pre_dedup_candidate_narrowing(
        stmt,
        source_id=source_id,
        received_at=received_at,
    )
    db.execute(
        text("SET LOCAL pg_trgm.word_similarity_threshold = :threshold"),
        {"threshold": threshold},
    )
    return db.execute(stmt).first()


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

    # Every workbook row is deliberately preserved as its own incident. It may
    # still be enriched by the extraction pipeline, but pre-extraction dedup
    # must never prevent that enrichment.
    if (getattr(msg, "raw_payload", None) or {}).get("origin") == "incident_excel_import":
        msg.dedup_checked_at = datetime.now(timezone.utc)
        db.commit()
        return False

    msg.dedup_checked_at = datetime.now(timezone.utc)

    best = find_pre_dedup_match(
        db,
        raw_message_id=raw_message_id,
        source_id=msg.source_id,
        received_at=msg.received_at,
        raw_text=msg.raw_text,
        threshold=threshold,
    )
    if best is None or best.score < threshold:
        db.commit()
        return False

    original_id = choose_pre_dedup_original_id(raw_message_id, best.id)
    if original_id is None:
        db.commit()
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
        db.commit()
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
