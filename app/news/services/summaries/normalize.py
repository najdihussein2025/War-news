from __future__ import annotations

import re
import unicodedata

from .dtos import NormalizedText

SEPARATOR = "\n"
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_LETTERS = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ة": "ه", "ى": "ي"})
_BULLETS = frozenset("•*◦▪●○◉▫■□◆◇🔸🔹🔵🟠⭕🏴⭐")
_DIACRITIC = re.compile(r"[\u064b-\u065f\u0670\u06d6-\u06ed]")


def normalize_summary_text(text: str) -> NormalizedText:
    chars: list[str] = []
    offsets: list[int] = []
    last_space = False
    last_newline = False
    for index, raw in enumerate(text or ""):
        ch = raw.translate(_DIGITS).translate(_LETTERS)
        if raw == "ـ" or _DIACRITIC.match(raw) or unicodedata.category(raw) in {"Mn", "Me"}:
            continue
        category = unicodedata.category(raw)
        is_emoji = category == "So" or (0x1F000 <= ord(raw) <= 0x1FAFF)
        if raw in _BULLETS or is_emoji or raw in "\r\n":
            if chars and not last_newline:
                chars.append(SEPARATOR); offsets.append(index)
            last_space, last_newline = False, True
            continue
        if ch.isspace():
            if chars and not last_space and not last_newline:
                chars.append(" "); offsets.append(index)
            last_space = True
            continue
        chars.append(ch); offsets.append(index)
        last_space = last_newline = False
    while chars and chars[-1] in {" ", SEPARATOR}:
        chars.pop(); offsets.pop()
    return NormalizedText("".join(chars), tuple(offsets), text or "")


def normalize_token(text: str, *, compact: bool = False) -> str:
    value = normalize_summary_text(text).text.replace("\n", " ")
    value = re.sub(r"\s+", " ", value).strip(" \t،,؛;:.!؟\"'«»()")
    return value.replace(" ", "") if compact else value


def village_key(text: str, *, compact: bool = False) -> str:
    value = re.sub(r"(^| )ال(?=\S{3,})", r"\1", normalize_token(text))
    return value.replace(" ", "") if compact else value
