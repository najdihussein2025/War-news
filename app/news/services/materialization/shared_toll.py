"""Ordering helpers for shared-toll (bulletin aggregate) groups."""

from __future__ import annotations

import re
from typing import Any

from app.core.text_normalization import normalize_arabic_text

_ARABIC_LETTERS = "ء-ي"


def first_mention_village_ids(
    raw_text: str | None,
    target_matches: list[dict[str, Any]],
) -> list[int]:
    """Matched village ids in the order the text first mentions them.

    Deterministic: sorts by the earliest position of each target's own text in the
    message (an attached و/ب/ل/ف/ك prefix is allowed), falling back to the
    extraction order for names that cannot be located. Duplicates keep their
    first position. The first id is the owner of a shared toll.
    """
    text = normalize_arabic_text(raw_text or "")
    ranked: list[tuple[int, int, int]] = []
    for index, item in enumerate(target_matches):
        village_id = item.get("matched_village_id")
        if not isinstance(village_id, int) or isinstance(village_id, bool):
            continue
        needle = normalize_arabic_text(str(item.get("raw_village_text") or ""))
        position = -1
        if needle:
            found = re.search(
                rf"(?<![{_ARABIC_LETTERS}])(?:و?[بلفك]?)?{re.escape(needle)}(?![{_ARABIC_LETTERS}])",
                text,
            )
            position = found.start() if found else -1
        ranked.append((position if position >= 0 else len(text) + index, index, village_id))
    return list(dict.fromkeys(village_id for _, _, village_id in sorted(ranked)))
