"""Persistence boundary for deterministic summary intake (shadow mode)."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select

from app.core.config import settings
from app.news.models.summary_bulletin import (
    SummaryBulletin, SummaryItem, SummaryItemOrigin, SummaryKind, SummaryModifier,
    SummaryResolution, SummaryReviewStatus, SummaryReviewTask, SummaryStatus,
)

from .crosscheck_service import ParserPair, crosscheck_summary, record_parser_misses
from .detection import detect_summary
from .gazetteer import build_gazetteer_snapshot
from .header_store import header_dictionary_for_session
from .lexicon import LEXICON
from .normalize import normalize_summary_text, normalize_token
from .parser import parse_summary
from .window import resolve_window

PARSER_VERSION = "summary-parser-1"
NOT_A_SUMMARY = "not_a_summary"


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
            SummaryBulletin.canonical_summary_id.is_(None),
            SummaryBulletin.status != SummaryStatus.failed,
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
        headers = header_dictionary_for_session(session)
        result = parse_summary(raw_text, gazetteer, headers, LEXICON, window.anchor_date)
        # False-positive guard: a real summary lists at least two (action, place)
        # pairs under at least one recognized header. Anything else (a news item
        # that merely says "ملخص") is left to Tier 1.
        recognized_headers = [h for h in result.headers if h.status == "approved"]
        if len(result.items) + len(result.unresolved_places) < 2 or not recognized_headers:
            summary.status = SummaryStatus.failed
            summary.last_error = NOT_A_SUMMARY
            session.flush()
            return SummaryIntakeResult("not_a_summary", summary.id, NOT_A_SUMMARY)
        reasons: list[dict] = []
        parser_pairs: list[ParserPair] = []
        position = 0
        for item in result.items:
            evidence = item.evidence_spans[0].text if item.evidence_spans else ""
            _assert_evidence(raw_text, evidence)
            session.add(SummaryItem(summary_id=summary.id, position=position, header_text=item.header_text,
                condition_id=item.condition_id, location_text=" | ".join(item.location_texts),
                primary_village_id=item.primary_village.id, secondary_village_id=item.secondary_village.id if item.secondary_village else None,
                modifier=_modifier(item), reported_count=item.reported_count, evidence_span=evidence,
                origin=SummaryItemOrigin.parser, resolution=SummaryResolution.resolved))
            parser_pairs.append(ParserPair(item.header_text, " | ".join(item.location_texts), item.condition_id,
                item.primary_village.id, item.secondary_village.id if item.secondary_village else None))
            position += 1
        section_of_place = {r.text: r.section_header for r in result.residual if r.kind == "unresolved_place" and r.section_header}
        for text in result.unresolved_places:
            _assert_evidence(raw_text, text)
            # Keep the section's action with the place so a reviewer only has to pick the village.
            header_text = section_of_place.get(text)
            entry = headers.resolve(header_text)[0] if header_text else None
            condition_id = entry.condition_ids[0] if entry is not None and entry.status == "approved" and len(entry.condition_ids) == 1 else None
            row = SummaryItem(summary_id=summary.id, position=position, location_text=text, header_text=header_text, condition_id=condition_id,
                evidence_span=text, origin=SummaryItemOrigin.parser, resolution=SummaryResolution.unresolved_location)
            session.add(row); session.flush(); reasons.append({"type": "unresolved_location", "item_ids": [row.id], "text": text})
            position += 1
        for text in result.unresolved_headers:
            _assert_evidence(raw_text, text)
            row = SummaryItem(summary_id=summary.id, position=position, header_text=text, location_text=text,
                evidence_span=text, origin=SummaryItemOrigin.parser, resolution=SummaryResolution.unknown_header)
            session.add(row); session.flush(); reasons.append({"type": "unknown_header", "item_ids": [row.id], "text": text})
            position += 1
        # Add-only LLM cross-check: it can append items or review reasons, never change the above.
        crosscheck = await crosscheck_summary(
            raw_text, parser_pairs, gazetteer=gazetteer, headers=headers, anchor_date=window.anchor_date,
            known_unresolved=[*result.unresolved_places, *result.unresolved_headers],
        )
        if crosscheck.error:
            summary.last_error = crosscheck.error
        for add in crosscheck.accepted:
            item = add.item
            session.add(SummaryItem(summary_id=summary.id, position=position, header_text=add.header,
                condition_id=item.condition_id, location_text=" | ".join(item.location_texts) or add.location,
                primary_village_id=item.primary_village.id, secondary_village_id=item.secondary_village.id if item.secondary_village else None,
                modifier=_modifier(item), reported_count=item.reported_count, evidence_span=add.evidence_span,
                origin=SummaryItemOrigin.llm_crosscheck, resolution=SummaryResolution.resolved))
            position += 1
        for add in crosscheck.review:
            resolution = SummaryResolution.unknown_header if add.reason == "unknown_header" else SummaryResolution.unresolved_location
            row = SummaryItem(summary_id=summary.id, position=position, header_text=add.header, location_text=add.location,
                evidence_span=add.evidence_span, origin=SummaryItemOrigin.llm_crosscheck, resolution=resolution)
            session.add(row); session.flush()
            reasons.append({"type": add.reason, "item_ids": [row.id], "text": add.evidence_span, "origin": "llm_crosscheck"})
            position += 1
        record_parser_misses(raw_message.id, crosscheck.accepted)
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
