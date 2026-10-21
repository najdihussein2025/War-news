"""Channel / page header registry.

A channel or page name («صفحة الإعلامي الشهيد علي شعيب») is never news content.
The list lives in ``terminology/source_headers.yaml`` — adding a header is one
line there. Every stage that reads a post body calls :func:`strip_source_headers`
first; ``raw_text`` itself is never rewritten.

Matching is tolerant of diacritics, hamza/alef forms, ة/ه, ي/ى, a missing or
present «صفحة», the «ال/ل/لل» prefix variants, glued words and the ``| - – —``
separators, and is not limited to the first line. This module must stay free of
database and other app imports so every layer can use it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parent
_DROPPED = re.compile(r"[ً-ْٰـ​-‏⁠﻿]")
_LETTER_MAP = str.maketrans("أإآٱةى", "ااااهي")
_SEPARATORS = r"[\s|\-–—:،]*"
# Residue glued to a header that is removed with it: «🔴 صفحة …:».
_LEADING_DECORATION = r"(?:[#🔴🔵🚨📌]+[ \t]*)*"
_TRAILING_SEPARATORS = r"[ \t:|\-–—•،]*"


@dataclass(frozen=True)
class FoldedText:
    source: str
    text: str
    offsets: tuple[int, ...]


def fold_with_offsets(text: str | None) -> FoldedText:
    """Header-matching normalization with a normalized-index -> source-index map."""
    source = text or ""
    chars: list[str] = []
    offsets: list[int] = []
    for index, char in enumerate(source):
        if _DROPPED.match(char):
            continue
        chars.append(char.translate(_LETTER_MAP))
        offsets.append(index)
    return FoldedText(source=source, text="".join(chars), offsets=tuple(offsets))


def fold(text: str | None) -> str:
    return fold_with_offsets(text).text


@lru_cache(maxsize=1)
def header_texts() -> tuple[str, ...]:
    data: Any = yaml.safe_load((_ROOT / "terminology" / "source_headers.yaml").read_text(encoding="utf-8"))
    entries = data.get("headers", []) if isinstance(data, dict) else []
    return tuple(str(item["text"]).strip() for item in entries if isinstance(item, dict) and item.get("text"))


def _header_pattern(header: str) -> str:
    tokens = fold(header).split()
    # «صفحة» is a label, not part of the name: always optional.
    tokens = [t for t in tokens if t != "صفحه"] or tokens
    anchor = next((i for i, token in enumerate(tokens) if "شهيد" in token), 0)
    parts: list[str] = []
    for index, token in enumerate(tokens):
        core = token[2:] if token.startswith("ال") and len(token) > 3 else token
        # «ال/ل/لل/الل» and glued spellings: «اللاعلامي»، «الاعلاميالشهيد».
        suffix = "ه?" if "شهيد" in core else ""  # «الشهيدة»
        piece = rf"(?:ا?ل{{0,2}})?{re.escape(core)}{suffix}{_SEPARATORS}"
        # Words before the martyr word («الإعلامي») are optional.
        parts.append(piece if index >= anchor else f"(?:{piece})?")
    return rf"(?:صفحه{_SEPARATORS})?" + "".join(parts)


@lru_cache(maxsize=1)
def header_regex() -> re.Pattern[str] | None:
    """Regex over *folded* text (see :func:`fold_with_offsets`)."""
    patterns = [_header_pattern(h) for h in header_texts()]
    if not patterns:
        return None
    return re.compile("|".join(f"(?:{p})" for p in patterns))


def reload_headers() -> None:
    """Drop caches (tests that swap the YAML)."""
    header_texts.cache_clear()
    header_regex.cache_clear()


def header_spans(text: str | None) -> list[tuple[int, int]]:
    """Source-text ``[start, end)`` ranges covered by a registered header."""
    folded = fold_with_offsets(text)
    pattern = header_regex()
    if pattern is None or not folded.text:
        return []
    spans: list[tuple[int, int]] = []
    for match in pattern.finditer(folded.text):
        if match.end() == match.start():
            continue
        start = folded.offsets[match.start()]
        end = folded.offsets[match.end() - 1] + 1
        spans.append((start, end))
    return spans


def span_in_header(text: str | None, start: int, end: int) -> bool:
    """True when ``[start, end)`` of *text* lies inside a registered header."""
    return any(h_start <= start and end <= h_end for h_start, h_end in header_spans(text))


def strip_source_headers(text: str | None) -> str:
    """*text* with every registered header (and its glued separators) removed.

    The rest stays verbatim so spans found in the result are substrings of the source.
    """
    source = text or ""
    spans = header_spans(source)
    if not spans:
        return source
    pieces: list[str] = []
    cursor = 0
    for start, end in spans:
        lead = re.search(rf"{_LEADING_DECORATION}$", source[cursor:start])
        if lead is not None:
            start = start - len(lead.group(0))
        pieces.append(source[cursor:start])
        trail = re.match(_TRAILING_SEPARATORS, source[end:])
        cursor = end + (len(trail.group(0)) if trail else 0)
    pieces.append(source[cursor:])
    return "".join(pieces).strip()
