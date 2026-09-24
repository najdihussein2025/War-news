"""Guard rule files against the corruption found on 2026-09-24.

A bad merge duplicated tier1_general_prompt.md, a commit replaced Arabic with
"?????", and tier1_multi_village.md carried double-encoded (mojibake) Arabic.
Existing tests feed canned model output, so none of this failed CI.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

RULES_DIR = Path(__file__).resolve().parents[1] / "app" / "core" / "llm_knowledge" / "rules"

# Arabic UTF-8 decoded as cp1252 shows up as Ã/Ø/Ù/Ú/Û followed by a
# continuation character (Latin-1 0x80-0xBF or a cp1252 0x80-0x9F symbol).
MOJIBAKE = re.compile(
    "[ÃØÙÚÛ][\u0080-¿ŒœŠšŸŽžƒ"
    "ˆ˜–—‘-„†-•…‰‹›"
    "€™]"
)
REPLACED_TEXT = re.compile(r"\?{3,}")
MIN_DUPLICATE_LINE_LENGTH = 40

# Known duplicated intro, reported 2026-09-24 and not yet fixed. Remove the
# entry once the file is cleaned so the guard covers it too.
KNOWN_DUPLICATED_FILES = {"combined_tier1_prompt.md"}

RULE_FILES = sorted(path for path in RULES_DIR.glob("*.md"))


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def test_rule_files_found() -> None:
    assert RULE_FILES


@pytest.mark.parametrize("path", RULE_FILES, ids=lambda path: path.name)
def test_rule_file_has_no_replaced_or_mojibake_text(path: Path) -> None:
    for number, line in enumerate(_lines(path), 1):
        assert not REPLACED_TEXT.search(line), f"{path.name}:{number} has '???' text"
        assert not MOJIBAKE.search(line), f"{path.name}:{number} has mojibake"


@pytest.mark.parametrize("path", RULE_FILES, ids=lambda path: path.name)
def test_rule_file_is_not_duplicated(path: Path) -> None:
    if path.name in KNOWN_DUPLICATED_FILES:
        pytest.skip("known duplicated file; see KNOWN_DUPLICATED_FILES")
    lines = [line.strip() for line in _lines(path)]
    non_empty = [line for line in lines if line]
    assert non_empty.count(non_empty[0]) == 1, f"{path.name} repeats its opening line"
    seen: dict[str, int] = {}
    for number, line in enumerate(lines, 1):
        if len(line) < MIN_DUPLICATE_LINE_LENGTH:
            continue
        assert line not in seen, (
            f"{path.name}:{number} duplicates line {seen[line]}"
        )
        seen[line] = number


def test_guard_detects_the_original_corruption() -> None:
    assert REPLACED_TEXT.search('such as "?? ?????? ?????? ?????"')
    assert MOJIBAKE.search("described `ØªÙ…Ø´ÙŠØ·` / sweeping")
    assert not MOJIBAKE.search("described `تمشيط` / sweeping")
