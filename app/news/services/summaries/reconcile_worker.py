"""Batch driver for the summary-reconcile-worker (one pass per call).

Picks canonical summaries that are due and reconciles each in its own
transaction. ``shadow`` mode dry-runs summaries that Tier 1 also processed;
``live`` mode really writes, but only for summaries the summary flow owns
(raw message ``summary_handled``). ``off`` is idle.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import exists, or_, select, update

from app.core.config import settings
from app.news.models import MessageStatus, RawMessage
from app.news.models.summary_bulletin import (
    SummaryBulletin,
    SummaryItem,
    SummaryReconciliationStatus,
    SummaryResolution,
    SummaryReviewStatus,
    SummaryReviewTask,
    SummaryStatus,
)

from .reconcile_service import reconcile_summary
from .routing import run_coroutine_sync

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5
DEFAULT_BATCH_LIMIT = 50


def due_summary_ids(session, *, mode: str, limit: int = DEFAULT_BATCH_LIMIT, now: datetime | None = None) -> list[int]:
    now = now or datetime.now(timezone.utc)
    open_task = exists().where(
        SummaryReviewTask.summary_id == SummaryBulletin.id,
        SummaryReviewTask.status == SummaryReviewStatus.open,
    )
    pending_item = exists().where(
        SummaryItem.summary_id == SummaryBulletin.id,
        SummaryItem.resolution == SummaryResolution.resolved,
        SummaryItem.reconciliation_status == SummaryReconciliationStatus.pending,
    )
    query = (
        select(SummaryBulletin.id)
        .join(RawMessage, RawMessage.id == SummaryBulletin.raw_message_id)
        .where(
            SummaryBulletin.canonical_summary_id.is_(None),
            SummaryBulletin.process_after <= now,
            SummaryBulletin.attempts < MAX_ATTEMPTS,
            or_(
                SummaryBulletin.status.in_([SummaryStatus.parsed, SummaryStatus.awaiting_window]),
                # needs_review only re-runs for items left pending once the task is closed
                (SummaryBulletin.status == SummaryStatus.needs_review) & ~open_task & pending_item,
            ),
        )
        .order_by(SummaryBulletin.process_after.asc(), SummaryBulletin.id.asc())
        .limit(limit)
    )
    if mode == "live":
        query = query.where(RawMessage.status == MessageStatus.summary_handled)
    else:  # shadow: dry-run each summary once, only those Tier 1 also handled
        query = query.where(
            RawMessage.status != MessageStatus.summary_handled, SummaryBulletin.shadow_result.is_(None)
        )
    return list(session.scalars(query))


def run_reconcile_batch(
    session_factory: Callable[[], object],
    *,
    mode: str | None = None,
    limit: int = DEFAULT_BATCH_LIMIT,
) -> dict[str, int | str]:
    """One sweep. Returns the standard ``processed / succeeded / failed`` shape."""
    mode = (mode or settings.summary_flow_mode or "off").lower()
    summary: dict[str, int | str] = {"mode": mode, "processed": 0, "succeeded": 0, "failed": 0, "skipped": 0}
    if mode not in {"shadow", "live"}:
        return summary
    with session_factory() as db:
        ids = due_summary_ids(db, mode=mode, limit=limit)
    for summary_id in ids:
        summary["processed"] += 1  # type: ignore[operator]
        try:
            with session_factory() as db:
                result = run_coroutine_sync(reconcile_summary(db, summary_id, dry_run=(mode == "shadow")))
                db.commit()
            if result.outcome.startswith("skipped"):
                summary["skipped"] += 1  # type: ignore[operator]
            else:
                summary["succeeded"] += 1  # type: ignore[operator]
            logger.info(
                "summary reconcile id=%s mode=%s outcome=%s counts=%s hidden=%s",
                summary_id, mode, result.outcome, result.counts, result.hidden,
            )
        except Exception as exc:
            summary["failed"] += 1  # type: ignore[operator]
            logger.exception("summary reconcile failed id=%s", summary_id)
            _record_failure(session_factory, summary_id, exc)
    return summary


def _record_failure(session_factory: Callable[[], object], summary_id: int, exc: Exception) -> None:
    try:
        with session_factory() as db:
            db.execute(
                update(SummaryBulletin)
                .where(SummaryBulletin.id == summary_id)
                .values(attempts=SummaryBulletin.attempts + 1, last_error=f"reconcile: {exc}"[:4000])
            )
            db.commit()
    except Exception:
        logger.exception("could not record reconcile failure for summary id=%s", summary_id)
