from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.text_normalization import normalize_arabic_text


@dataclass(frozen=True)
class CasualtyTransitionBackstopResult:
    plausible: bool
    matched_keywords: tuple[str, ...]


_KEYWORD_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "استشهاد أحد جريحي/الجرحى",
        re.compile(r"استشهاد احد (?:جريحي|الجرحى)"),
    ),
    (
        "وفاة أحد المصابين متأثراً بجراحه",
        re.compile(r"وفاه احد المصابين.{0,40}متاثر.{0,10}بجراح"),
    ),
    (
        "فارق أحد الجرحى الحياة",
        re.compile(r"فارق احد الجرحى الحياه"),
    ),
    (
        "توفي أحد الجرحى/المصابين",
        re.compile(r"توف[ىي] احد (?:الجرحى|المصابين)"),
    ),
    (
        "وفاة/توفي جريح متأثراً بإصابته أو بجراحه",
        re.compile(r"(?:وفاه|توف[ىي]).{0,20}جريح.{0,40}متاثر.{0,10}(?:باصابت|بجراح)"),
    ),
    (
        "استشهاد/وفاة متأثراً بجراحه التي أصيب بها",
        re.compile(r"(?:استشهاد|استشهد|وفاه|توف[ىي]).{0,60}متاثر.{0,10}بجراح.{0,40}اصيب بها"),
    ),
    (
        "فارق الحياة بعد إصابة سابقة",
        re.compile(r"فارق الحياه.{0,60}(?:جرح|اصيب|اصابته|بجراح)"),
    ),
)


def casualty_transition_keyword_labels() -> tuple[str, ...]:
    return tuple(label for label, _ in _KEYWORD_PATTERNS)


def detect_casualty_transition_backstop(
    text: str | None,
) -> CasualtyTransitionBackstopResult:
    normalized = normalize_arabic_text(text or "")
    if not normalized:
        return CasualtyTransitionBackstopResult(
            plausible=False,
            matched_keywords=(),
        )

    matches = tuple(
        label
        for label, pattern in _KEYWORD_PATTERNS
        if pattern.search(normalized)
    )
    return CasualtyTransitionBackstopResult(
        plausible=bool(matches),
        matched_keywords=matches,
    )
