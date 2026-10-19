"""Fail when source or data files contain UTF-8 Arabic that was re-decoded as cp1252/latin-1."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ("app", "scripts", "tests", "Data")
SUFFIXES = {".py", ".yaml", ".yml", ".md", ".json", ".sql"}
MARKER = re.compile(
    "[ÃØÙÚÛ][\u0080-¿ŒœŠšŸŽž"
    "ƒˆ˜–—‘-„†-•…‰‹›€™]"
)


def _encode(ch: str) -> bytes:
    try:
        return ch.encode("cp1252")
    except UnicodeError:
        if ord(ch) < 256:
            return bytes([ord(ch)])
        raise


def _round_trips_to_arabic(line: str) -> bool:
    candidate = line
    for _ in range(4):
        try:
            candidate = b"".join(_encode(c) for c in candidate).decode("utf-8")
        except UnicodeError:
            segments = re.findall(r"[^\U00010000-\U0010ffff←-⇿]+", candidate)
            for segment in segments:
                if MARKER.search(segment) and _round_trips_to_arabic(segment):
                    return True
            return False
        if any("؀" <= c <= "ۿ" for c in candidate):
            return True
    return False


def _files():
    for directory in SCAN_DIRS:
        for path in (ROOT / directory).rglob("*"):
            if path.suffix in SUFFIXES and path.is_file() and "__pycache__" not in path.parts:
                yield path


def test_no_arabic_mojibake_in_source_and_data() -> None:
    offenders: list[str] = []
    for path in _files():
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), 1):
            if MARKER.search(line) and _round_trips_to_arabic(line):
                offenders.append(f"{path.relative_to(ROOT)}:{number}")
    assert not offenders, "mojibake that round-trips into Arabic: " + ", ".join(offenders[:20])


def test_detector_catches_known_corruption() -> None:
    corrupted = "تمشيط".encode("utf-8").decode("cp1252")
    assert MARKER.search(corrupted)
    assert _round_trips_to_arabic(corrupted)
    assert not MARKER.search("تمشيط")
