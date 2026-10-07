"""Corpus invariants for the deterministic summary parser (Step 1e).

Each check returns human-readable violations; an empty list means the invariant
holds. Header-like lines are recomputed here from the text with the same shared
predicate the parser uses, so a parser that silently let a place inherit a
header across a barrier is caught rather than trusted.
"""
from __future__ import annotations

import re

from .dtos import ParseResult
from .gazetteer import GazetteerSnapshot
from .headers import HeaderDictionarySnapshot
from .normalize import normalize_summary_text
from .parser import _has_section_bullet, _preclean_text, is_header_like


def header_like_starts(text: str, gazetteer: GazetteerSnapshot, headers: HeaderDictionarySnapshot) -> list[int]:
    """Original-text offsets of every header-like line."""
    normalized = normalize_summary_text(_preclean_text(text, gazetteer, headers))
    starts = []
    for line in re.finditer(r"[^\n]+", normalized.text):
        if is_header_like(line.group(0), _has_section_bullet(normalized, line.start()), gazetteer, headers):
            starts.append(normalized.offsets[line.start()])
    return starts


def header_provenance_violations(text: str, result: ParseResult, gazetteer: GazetteerSnapshot,
                                 headers: HeaderDictionarySnapshot) -> list[str]:
    """A resolved item's header must be at or after the nearest header-like line above its evidence."""
    barriers = sorted({*header_like_starts(text, gazetteer, headers), *(h.start for h in result.headers)})
    violations = []
    for item in result.items:
        for evidence, header in zip(item.evidence_spans, item.header_spans):
            if header is None:
                continue
            nearest = max((b for b in barriers if b <= evidence.start), default=None)
            if nearest is not None and header[0] < nearest:
                violations.append(f"condition {item.condition_id} at {item.primary_village.name_ar!r} read under header "
                                  f"@{header[0]} but a header-like line starts @{nearest}")
    return violations


def residual_header_violations(text: str, result: ParseResult, gazetteer: GazetteerSnapshot,
                               headers: HeaderDictionarySnapshot) -> list[str]:
    """A residual entry's section_header must be the nearest header-like line above its offsets."""
    barriers = sorted({*header_like_starts(text, gazetteer, headers), *(h.start for h in result.headers)})
    by_start = {h.start: h.text for h in result.headers}
    violations = []
    for entry in result.residual:
        nearest = max((b for b in barriers if b <= entry.offsets[0]), default=None)
        expected = by_start.get(nearest) if nearest is not None else None
        if entry.section_header != expected:
            violations.append(f"{entry.kind} {entry.text!r} labelled {entry.section_header!r}, nearest header is {expected!r}")
    return violations
