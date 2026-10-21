"""Deterministic text preparation shared by LLM-facing pipeline stages.

The returned text is a disposable prompt copy: callers must keep ``raw_text``
for storage and for displaying source evidence.
"""
from __future__ import annotations

import re

from app.core.llm_knowledge.source_headers import strip_source_headers

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def clean_message_text(text: str | None) -> str:
    """Remove registered channel/page headers and normalize digits for model input.

    Headers come from ``terminology/source_headers.yaml`` and are removed wherever
    they appear, whatever their spelling (see ``source_headers``).
    """
    lines = strip_source_headers((text or "").replace("\r\n", "\n").replace("\r", "\n")).split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"(?m)^\s*#\S+(?:\s+#\S+)*\s*$", "", cleaned)
    cleaned = re.sub(r"(?im)\s+(?:video|فيديو)\s*$", "", cleaned).strip()
    return cleaned.translate(_DIGITS)
