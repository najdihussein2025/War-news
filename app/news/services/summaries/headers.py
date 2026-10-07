from __future__ import annotations

from pathlib import Path
import re
from typing import Iterable

import yaml

from .dtos import HeaderEntry
from .normalize import normalize_token


class HeaderDictionarySnapshot:
    def __init__(self, entries: Iterable[HeaderEntry], action_cores: Iterable[HeaderEntry] = (), header_fillers: Iterable[str] = ()) -> None:
        self.entries = tuple(entries)
        self.by_name = {normalize_token(e.normalized_header): e for e in self.entries}
        self.action_cores = tuple(action_cores)
        self.header_fillers = tuple(sorted((normalize_token(x) for x in header_fillers), key=len, reverse=True))

    def match(self, candidate: str, *, approved_only: bool = False) -> tuple[HeaderEntry | None, str]:
        value = normalize_token(candidate)
        choices = [e for key, e in self.by_name.items() if value == key]
        if approved_only: choices = [e for e in choices if e.status == "approved"]
        if not choices: return None, ""
        entry = max(choices, key=lambda e: len(normalize_token(e.normalized_header)))
        return entry, value[len(normalize_token(entry.normalized_header)):].strip()

    def match_grammar(self, candidate: str) -> HeaderEntry | None:
        value = f" {normalize_token(candidate).replace('+', ' و ')} "
        condition_ids: list[int] = []
        for core in sorted(self.action_cores, key=lambda x: len(normalize_token(x.normalized_header)), reverse=True):
            phrase = normalize_token(core.normalized_header)
            words=phrase.split()
            first=words[0][2:] if words[0].startswith("ال") and len(words[0])>3 else words[0]
            flexible=" ".join([rf"(?:ال)?{re.escape(first)}",*(re.escape(x) for x in words[1:])])
            pattern = rf"(?<![\u0600-\u06ff]){flexible}(?![\u0600-\u06ff])"
            if re.search(pattern, value):
                value = re.sub(pattern, " ", value)
                condition_ids.extend(core.condition_ids)
        for filler in self.header_fillers:
            words=filler.split()
            first=words[0][2:] if words[0].startswith("ال") and len(words[0])>3 else words[0]
            flexible=" ".join([rf"(?:ال)?{re.escape(first)}",*(re.escape(x) for x in words[1:])])
            value = re.sub(rf"(?<![\u0600-\u06ff]){flexible}(?![\u0600-\u06ff])", " ", value)
        value = re.sub(r"[+\s]+", " ", value).strip()
        value = re.sub(r"(^| )و(?= |$)", " ", value).strip(" -–— ")
        if not condition_ids or value:
            return None
        return HeaderEntry(normalize_token(candidate), tuple(dict.fromkeys(condition_ids)), "approved", "header grammar")

    def has_action_core(self, candidate: str) -> bool:
        """True when any action core occurs in the text, even amid other words."""
        value = f" {normalize_token(candidate).replace('+', ' و ')} "
        for core in self.action_cores:
            words = normalize_token(core.normalized_header).split()
            first = words[0][2:] if words[0].startswith("ال") and len(words[0]) > 3 else words[0]
            flexible = " ".join([rf"(?:ال)?{re.escape(first)}", *(re.escape(x) for x in words[1:])])
            if re.search(rf"(?<![؀-ۿ]){flexible}(?![؀-ۿ])", value):
                return True
        return False

    def resolve(self, candidate: str) -> tuple[HeaderEntry | None, str]:
        exact, note = self.match(candidate)
        if exact is not None and exact.status == "approved":
            return exact, note
        grammatical=self.match_grammar(candidate)
        return (grammatical, "") if grammatical is not None else (exact,note)

    def suffix_match(self, before_colon: str) -> tuple[int, HeaderEntry, str] | None:
        words = before_colon.split()
        for size in range(min(18, len(words)), 0, -1):
            candidate = " ".join(words[-size:])
            entry, _ = self.resolve(candidate)
            if entry is not None:
                return len(before_colon) - len(candidate), entry, candidate
        return None


def load_header_dictionary(path: str | Path) -> HeaderDictionarySnapshot:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    special = {k: v for item in data if isinstance(item, dict) for k, v in item.items() if k in {"action_cores", "header_fillers"}}
    entries = [x for x in data if isinstance(x, dict) and "normalized_header" in x]
    cores = [HeaderEntry(normalize_token(x["core"]), tuple(x["condition_ids"]), "approved") for x in special.get("action_cores", [])]
    return HeaderDictionarySnapshot((HeaderEntry(normalize_token(x["normalized_header"]), tuple(x.get("condition_ids", [])), x["status"], x.get("note", "")) for x in entries), cores, special.get("header_fillers", []))


def default_header_dictionary() -> HeaderDictionarySnapshot:
    root = Path(__file__).resolve().parents[3] / "core" / "llm_knowledge" / "terminology" / "summary_headers.yaml"
    return load_header_dictionary(root)
