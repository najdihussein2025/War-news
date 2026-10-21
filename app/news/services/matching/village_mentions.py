"""Exact gazetteer mention scanning for arbitrary bulletin text.

This deliberately discovers only exact canonical/alias forms.  Fuzzy matching
remains the responsibility of :class:`MatchingService` once a mention exists.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.text_normalization import normalize_arabic_text


@dataclass(frozen=True)
class VillageMention:
    text: str
    start: int
    end: int
    acs_codes: tuple[int, ...]
    ambiguous: bool


_ROOT = Path(__file__).resolve().parents[4]
_PREFIXES = "وبلف"


@lru_cache(maxsize=1)
def _forms() -> dict[str, tuple[int, ...]]:
    """Canonical names and active location aliases, keyed exactly as matched."""
    forms: dict[str, set[int]] = {}
    for row in json.loads((_ROOT / "Data" / "Villages.json").read_text(encoding="utf-8")):
        code = int(row["acs_code"])
        for field in ("ref_name_ar", "acs_name", "cad_name"):
            value = row.get(field)
            if value and any("\u0600" <= char <= "\u06ff" for char in value):
                forms.setdefault(normalize_arabic_text(value), set()).add(code)
    for row in json.loads((_ROOT / "Data" / "VillageLocationAliases.json").read_text(encoding="utf-8")):
        value = row.get("alias_text")
        if value:
            forms.setdefault(normalize_arabic_text(value), set()).add(int(row["parent_acs_code"]))
    return {key: tuple(sorted(value)) for key, value in forms.items() if key}


def _token_spans(text: str) -> list[tuple[int, int]]:
    return [(match.start(), match.end()) for match in re.finditer(r"[\u0600-\u06ff]+", text)]


def find_village_mentions(text: str) -> list[VillageMention]:
    """Return non-overlapping longest exact gazetteer mentions with offsets.

    Leading conjunction/preposition particles are removed only for lookup, while
    returned offsets preserve the literal village text (``بالخيام`` → ``الخيام``).
    """
    forms = _forms()
    tokens = _token_spans(text or "")
    hits: list[VillageMention] = []
    index = 0
    while index < len(tokens):
        best: VillageMention | None = None
        for end_index in range(len(tokens), index, -1):
            start, _ = tokens[index]
            _, end = tokens[end_index - 1]
            literal = text[start:end]
            normalized = normalize_arabic_text(literal)
            stripped = normalized
            while len(stripped) > 2 and stripped[:1] in _PREFIXES:
                stripped = stripped[1:]
            codes = forms.get(normalized) or forms.get(stripped)
            if not codes:
                continue
            offset = len(normalized) - len(stripped) if stripped != normalized else 0
            mention_start = start + offset
            best = VillageMention(text=text[mention_start:end], start=mention_start, end=end, acs_codes=codes, ambiguous=len(codes) > 1)
            break
        if best is not None:
            hits.append(best)
            index = next((position for position, span in enumerate(tokens) if span[0] >= best.end), len(tokens))
        else:
            index += 1
    return hits
