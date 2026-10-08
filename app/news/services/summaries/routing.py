"""Route detected summary bulletins away from Tier 1 (SUMMARY_FLOW_MODE).

``off``    - nothing happens.
``shadow`` - intake runs and the message continues through Tier 1 unchanged.
``live``   - a real summary is owned by the summary flow: its raw message becomes
             ``summary_handled`` (no sweep selects that status). A failed or
             false-positive summary falls back to Tier 1 so no news is lost.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy import select

from app.core.config import settings
from app.news.models import MessageStatus
from app.news.models.summary_bulletin import SummaryBulletin, SummaryStatus

from .intake_service import intake_summary

logger = logging.getLogger(__name__)

# Intake outcomes that mean "this is not (usable as) a summary": Tier 1 handles it.
FALLBACK_OUTCOMES = frozenset({"not_summary", "not_a_summary", "failed"})


@dataclass(frozen=True)
class SummaryRouting:
    handled: bool
    outcome: str
    summary_id: int | None = None


def run_coroutine_sync(coro: Any) -> Any:
    """Run a coroutine to completion from sync code, even inside a running event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    box: dict[str, Any] = {}

    def runner() -> None:
        try:
            box["value"] = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001 - re-raised below
            box["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box["value"]


def route_summary(session, message, *, mode: str | None = None) -> SummaryRouting:
    """Run intake for ``message`` and decide whether the summary flow owns it.

    Does not commit; the caller does. A ``handled`` result has already moved the
    message to ``summary_handled`` and cleared its pipeline claim.
    """
    mode = (mode or settings.summary_flow_mode or "off").lower()
    if mode not in {"shadow", "live"}:
        return SummaryRouting(False, "off")
    result = run_coroutine_sync(intake_summary(session, message))
    outcome, summary_id = result.outcome, result.summary_id
    if outcome == "already_processed" and summary_id is not None:
        existing = session.scalar(select(SummaryBulletin).where(SummaryBulletin.id == summary_id))
        if existing is not None and existing.status == SummaryStatus.failed:
            outcome = "failed"
    if mode == "shadow":
        return SummaryRouting(False, outcome, summary_id)
    if outcome in FALLBACK_OUTCOMES:
        if outcome == "failed":
            logger.error(
                "summary flow failed for raw_message_id=%s summary_id=%s error=%s; falling back to Tier 1",
                message.id, summary_id, getattr(result, "error", None),
            )
        return SummaryRouting(False, outcome, summary_id)
    message.status = MessageStatus.summary_handled
    message.error_message = None
    message.processing_claim_stage = None
    message.processing_claimed_at = None
    message.processing_claimed_by = None
    session.add(message)
    logger.info("raw_message_id=%s handled by summary flow outcome=%s summary_id=%s", message.id, outcome, summary_id)
    return SummaryRouting(True, outcome, summary_id)


def build_summary_router(session) -> Callable[[Any], bool] | None:
    """A ``message -> handled`` callable for sequential Tier 1 callers (None when off)."""
    if (settings.summary_flow_mode or "off").lower() not in {"shadow", "live"}:
        return None

    def router(message: Any) -> bool:
        try:
            decision = route_summary(session, message)
            session.commit()
            return decision.handled
        except Exception:
            session.rollback()
            logger.warning("summary routing failed raw_message_id=%s; continuing Tier 1", getattr(message, "id", None), exc_info=True)
            return False

    return router
