from __future__ import annotations

from pathlib import Path
from typing import Iterable

import yaml

from .dtos import HeaderEntry
from .normalize import normalize_token


class HeaderDictionarySnapshot:
    def __init__(self, entries: Iterable[HeaderEntry]) -> None:
        self.entries = tuple(entries)
        self.by_name = {normalize_token(e.normalized_header): e for e in self.entries}

    def match(self, candidate: str, *, approved_only: bool = False) -> tuple[HeaderEntry | None, str]:
        value = normalize_token(candidate)
        choices = [e for key, e in self.by_name.items() if value == key or value.startswith(key + " ")]
        if approved_only: choices = [e for e in choices if e.status == "approved"]
        if not choices: return None, ""
        entry = max(choices, key=lambda e: len(normalize_token(e.normalized_header)))
        return entry, value[len(normalize_token(entry.normalized_header)):].strip()


def load_header_dictionary(path: str | Path) -> HeaderDictionarySnapshot:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    return HeaderDictionarySnapshot(HeaderEntry(normalize_token(x["normalized_header"]), tuple(x.get("condition_ids", [])), x["status"], x.get("note", "")) for x in data)


def default_header_dictionary() -> HeaderDictionarySnapshot:
    root = Path(__file__).resolve().parents[3] / "core" / "llm_knowledge" / "terminology" / "summary_headers.yaml"
    return load_header_dictionary(root)
