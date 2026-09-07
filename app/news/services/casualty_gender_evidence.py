from __future__ import annotations

import re

from app.llm.dtos import ExtractionCasualties


_ARABIC_LETTER = r"\u0600-\u06ff"


def _standalone(word: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?<![{_ARABIC_LETTER}])(?:و)?(?:{word})(?![{_ARABIC_LETTER}])"
    )


_EXPLICIT_FORMS: dict[str, tuple[tuple[int, re.Pattern[str]], ...]] = {
    "male_deaths": ((1, _standalone("شهيد")), (2, _standalone("شهيدان|شهيدين"))),
    "female_deaths": ((1, _standalone("شهيدة")), (2, _standalone("شهيدتان|شهيدتين"))),
    "male_injuries": ((1, _standalone("جريح")), (2, _standalone("جريحان|جريحين"))),
    "female_injuries": ((1, _standalone("جريحة")), (2, _standalone("جريحتان|جريحتين"))),
}

_COUNTED_PLURALS = {
    "male_deaths": "شهداء",
    "female_deaths": "شهيدات",
    "male_injuries": "جرحى",
    "female_injuries": "جريحات",
}


def _arabic_indic_number(value: int) -> str:
    return str(value).translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))


def _has_counted_plural(text: str, *, count: int, word: str) -> bool:
    numbers = rf"(?:{count}|{_arabic_indic_number(count)})"
    return bool(
        re.search(rf"{numbers}\s*{re.escape(word)}", text)
        or re.search(rf"{re.escape(word)}\s*{numbers}", text)
    )


def apply_explicit_arabic_gender_evidence(
    text: str,
    casualties: ExtractionCasualties,
) -> ExtractionCasualties:
    """Fill gender only when an unambiguous Arabic singular/dual form covers the total."""
    values = casualties.model_dump(mode="python")
    for outcome, reported_key, total_key in (
        ("deaths", "deaths", "total_deaths"),
        ("injuries", "injuries", "total_injuries"),
    ):
        total = values.get(total_key) or values.get(reported_key)
        if not isinstance(total, int) or total <= 0:
            continue
        male_key = f"male_{outcome}"
        female_key = f"female_{outcome}"
        if total <= 2:
            male_explicit = any(
                count == total and pattern.search(text)
                for count, pattern in _EXPLICIT_FORMS[male_key]
            )
            female_explicit = any(
                count == total and pattern.search(text)
                for count, pattern in _EXPLICIT_FORMS[female_key]
            )
        else:
            # Masculine Arabic plurals can represent a mixed-gender group, so
            # they do not prove that every casualty is male. Feminine plurals
            # are explicit and can safely cover the reported total.
            male_explicit = False
            female_explicit = _has_counted_plural(
                text,
                count=total,
                word=_COUNTED_PLURALS[female_key],
            )
        if male_explicit == female_explicit:
            continue
        child_count = values.get(f"children_{outcome}")
        adult_count = total - child_count if isinstance(child_count, int) else total
        confirmed_count = adult_count if adult_count > 0 else None
        if male_explicit:
            values[male_key] = confirmed_count
            values[female_key] = None
        else:
            values[female_key] = confirmed_count
            values[male_key] = None
    return ExtractionCasualties.model_validate(values)
