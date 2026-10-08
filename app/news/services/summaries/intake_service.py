"""Persistence boundary for deterministic summary intake (shadow mode)."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import yaml

from sqlalchemy import select

from app.core.config import settings
from app.news.models.summary_bulletin import (
    SummaryBulletin, SummaryItem, SummaryItemOrigin, SummaryKind, SummaryModifier,
    SummaryResolution, SummaryReviewStatus, SummaryReviewTask, SummaryStatus,
)

from .detection import detect_summary
from .gazetteer import build_gazetteer_snapshot
from .headers import default_header_dictionary
from .normalize import normalize_summary_text, normalize_token
from .parser import parse_summary
from .window import resolve_window

PARSER_VERSION = "summary-parser-1"
LEXICON = yaml.safe_load((Path(__file__).resolve().parents[3] / "core" / "llm_knowledge" / "terminology" / "summary_location_lexicon.yaml").read_text(encoding="utf-8"))


@dataclass(frozen=True)
class SummaryIntakeResult:
    outcome: str
    summary_id: int | None = None
    error: str | None = None


def _fingerprint(raw_text: str) -> str:
    # Parser normalization removes tashkeel/tatweel, folds Arabic letters/digits,
    # normalizes bullets and collapses whitespace. It intentionally retains text
    # evidence; only channel boilerplate is stripped by parser pre-cleaning.
    canonical = " ".join(normalize_summary_text(raw_text).text.split())
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _kind(rule: str) -> SummaryKind:
    if rule in {"default", "explicit_date"}:
        return SummaryKind.full_day
    if rule:
        return SummaryKind.partial
    return SummaryKind.unknown


def _modifier(item) -> SummaryModifier:
    if item.secondary_village is not None:
        return SummaryModifier.between
    if any(normalize_token(q) in {"اطراف", "أطراف"} for q in item.qualifiers):
        return SummaryModifier.outskirts
    return SummaryModifier.none


def _assert_evidence(raw_text: str, evidence: str) -> None:
    if not evidence or evidence not in raw_text:
        raise ValueError("summary parser evidence span is not a verbatim substring of raw_message.raw_text")


async def intake_summary(session, raw_message) -> SummaryIntakeResult:
    """Persist a parser result without ever changing the legacy message flow."""
    raw_text = raw_message.raw_text or ""
    if not detect_summary(raw_text).is_summary:
        return SummaryIntakeResult("not_summary")
    existing = session.scalar(select(SummaryBulletin).where(SummaryBulletin.raw_message_id == raw_message.id))
    if existing is not None:
        return SummaryIntakeResult("already_processed", existing.id)
    fingerprint = _fingerprint(raw_text)
    summary = SummaryBulletin(
        raw_message_id=raw_message.id, source_id=raw_message.source_id,
        channel=raw_message.source_name, fingerprint=fingerprint,
        status=SummaryStatus.detected, parser_version=PARSER_VERSION,
    )
    session.add(summary)
    try:
        session.flush()
        cutoff = (raw_message.message_datetime or summary.created_at) - timedelta(hours=48)
        canonical = session.scalar(select(SummaryBulletin).where(
            SummaryBulletin.fingerprint == fingerprint,
            SummaryBulletin.id != summary.id,
            SummaryBulletin.created_at >= cutoff,
        ).order_by(SummaryBulletin.created_at.asc()))
        if canonical is not None:
            summary.canonical_summary_id = canonical.id
            summary.status = SummaryStatus.skipped_repost
            session.flush()
            return SummaryIntakeResult("skipped_repost", summary.id)
        posted = raw_message.message_datetime or raw_message.received_at
        window = resolve_window(raw_text, posted)
        summary.kind = _kind(window.rule)
        summary.window_start, summary.window_end = window.start, window.end
        summary.window_basis = window.rule
        summary.process_after = window.end + timedelta(minutes=settings.summary_reconcile_delay_minutes)
        gazetteer = build_gazetteer_snapshot(session)
        result = parse_summary(raw_text, gazetteer, default_header_dictionary(), LEXICON, window.anchor_date)
        reasons: list[dict] = []
        for position, item in enumerate(result.items):
            evidence = item.evidence_spans[0].text if item.evidence_spans else ""
            _assert_evidence(raw_text, evidence)
            session.add(SummaryItem(summary_id=summary.id, position=position, header_text=item.header_text,
                condition_id=item.condition_id, location_text=" | ".join(item.location_texts),
                primary_village_id=item.primary_village.id, secondary_village_id=item.secondary_village.id if item.secondary_village else None,
                modifier=_modifier(item), reported_count=item.reported_count, evidence_span=evidence,
                origin=SummaryItemOrigin.parser, resolution=SummaryResolution.resolved))
        for text in result.unresolved_places:
            _assert_evidence(raw_text, text)
            row = SummaryItem(summary_id=summary.id, position=len(result.items) + len(reasons), location_text=text,
                evidence_span=text, origin=SummaryItemOrigin.parser, resolution=SummaryResolution.unresolved_location)
            session.add(row); session.flush(); reasons.append({"type": "unresolved_location", "item_ids": [row.id], "text": text})
        for text in result.unresolved_headers:
            _assert_evidence(raw_text, text)
            row = SummaryItem(summary_id=summary.id, position=len(result.items) + len(reasons), header_text=text, location_text=text,
                evidence_span=text, origin=SummaryItemOrigin.parser, resolution=SummaryResolution.unknown_header)
            session.add(row); session.flush(); reasons.append({"type": "unknown_header", "item_ids": [row.id], "text": text})
        if reasons:
            session.add(SummaryReviewTask(summary_id=summary.id, reasons=reasons, status=SummaryReviewStatus.open))
            summary.status = SummaryStatus.needs_review
        else:
            summary.status = SummaryStatus.parsed
        session.flush()
        return SummaryIntakeResult(summary.status.value, summary.id)
    except Exception as exc:
        summary.status = SummaryStatus.failed
        summary.last_error = str(exc)[:4000]
        session.flush()
        return SummaryIntakeResult("failed", summary.id, summary.last_error)
