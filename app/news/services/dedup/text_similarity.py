from __future__ import annotations

import re

from app.core.text_normalization import normalize_arabic_text
from app.core.text_sanitizer import strip_emoji_and_pictographs
from app.news.services.clustering.raw_message_embedding_service import strip_boilerplate

TOKEN_RE = re.compile(r"[\u0600-\u06ffa-zA-Z0-9]+")

STOPWORDS = {
    "a",
    "an",
    "and",
    "at",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "the",
    "to",
    "with",
    "\u0627\u062b\u0631",
    "\u0627\u0644\u064a",
    "\u0627\u0646",
    "\u0628\u0639\u062f",
    "\u0628\u0644\u062f\u0629",
    "\u0641\u064a",
    "\u0642\u0628\u0644",
    "\u0645\u0639",
    "\u0645\u0646",
    "\u0639\u0627\u062c\u0644",
    "\u0639\u0627\u0645",
    "\u0639\u0644\u0649",
    "\u0639\u0646",
    "\u0645\u0631\u0627\u0633\u0644",
    "\u0645\u0631\u0627\u0633\u0644\u0629",
    "\u0627\u0644\u0645\u0646\u0627\u0631",
    "\u0637\u0631\u064a\u0642",
}


def event_token_similarity(left: str | None, right: str | None) -> float | None:
    """Return containment-style overlap for domain event wording variants."""
    left_tokens = _event_tokens(left)
    right_tokens = _event_tokens(right)
    smaller = min(len(left_tokens), len(right_tokens))
    if smaller < 4:
        return None
    shared = left_tokens & right_tokens
    if len(shared) < 4:
        return None
    return len(shared) / float(smaller)


def _event_tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    cleaned = strip_boilerplate(strip_emoji_and_pictographs(text))
    normalized = normalize_arabic_text(cleaned).lower()
    return {
        token
        for token in TOKEN_RE.findall(normalized)
        if len(token) > 1 and token not in STOPWORDS
    }
