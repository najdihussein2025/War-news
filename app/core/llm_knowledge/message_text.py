"""Deterministic text preparation shared by LLM-facing pipeline stages.

The returned text is a disposable prompt copy: callers must keep ``raw_text``
for storage and for displaying source evidence.  Header removal is deliberately
limited to leading lines so a quoted channel name in the reported event is not
silently changed.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
from typing import Any

import yaml


_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_ROOT = Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def _headers() -> tuple[str, ...]:
    data: Any = yaml.safe_load((_ROOT / "terminology" / "source_headers.yaml").read_text(encoding="utf-8"))
    entries = data.get("headers", []) if isinstance(data, dict) else []
    return tuple(str(item["text"]).strip() for item in entries if isinstance(item, dict) and item.get("text"))


def clean_message_text(text: str | None) -> str:
    """Remove known leading source labels and normalize digits for model input."""
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    known = _headers()
    while lines:
        candidate = lines[0].strip()
        normalized = re.sub(r"^[#🔴🔵🚨📌\s]+", "", candidate).strip()
        if not candidate:
            lines.pop(0)
            continue
        header = next((item for item in known if normalized == item or normalized.startswith(item + ":") or normalized.startswith(item + " ")), None)
        if header:
            remainder = normalized[len(header):].lstrip(" :|-—–•\t")
            if remainder:
                lines[0] = remainder
                break
            lines.pop(0)
            continue
        break
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"(?m)^\s*#\S+(?:\s+#\S+)*\s*$", "", cleaned)
    cleaned = re.sub(r"(?im)\s+(?:video|فيديو)\s*$", "", cleaned).strip()
    return cleaned.translate(_DIGITS)
