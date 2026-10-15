from __future__ import annotations

import re

from app.core.llm_knowledge.loader import terms_by_category
from app.core.text_normalization import normalize_arabic_text
from app.llm.dtos import ExtractionCasualties, ExtractionResult, ExtractionSubEvent


_ARABIC_LETTER = r"\u0600-\u06ff"
_CASUALTY_GENDER_YAML = "terminology/casualty_gender.yaml"

# Grammatical masculine forms (for example ``شهيدان``) are not demographic
# evidence.  These deliberately narrow lists are the only automatic gender
# evidence accepted from text; children may overlap female/male only when the
# source explicitly says so.
_EXPLICIT_DEMOGRAPHIC_TERMS = {
    "male": ("رجل", "رجال", "شاب", "شبان", "والد", "زوج"),
    "female": ("امرأة", "سيدة", "سيدات", "نساء", "فتاة", "شابة", "والدة", "زوجة"),
    "children": ("طفل", "طفلة", "أطفال", "طفلان", "طفلين", "رضيع", "رضيعة", "قاصر", "فتى", "ولد"),
}


def reject_unproven_demographics(text: str, casualties: ExtractionCasualties) -> ExtractionCasualties:
    """Drop LLM demographic claims not supported by explicit demographic words.

    A masculine casualty noun is Arabic grammar, not proof that the people are
    male.  This guard is intentionally conservative: it removes unsupported
    values instead of putting the incident in the verification queue.
    """
    normalized = normalize_arabic_text(text or "")
    values = casualties.model_dump(mode="python")
    for group, terms in _EXPLICIT_DEMOGRAPHIC_TERMS.items():
        supported = any(_standalone(re.escape(normalize_arabic_text(term))).search(normalized) for term in terms)
        if not supported:
            values[f"{group}_deaths"] = None
            values[f"{group}_injuries"] = None
    return ExtractionCasualties.model_validate(values)

# ---------------------------------------------------------------------------
# Fragment classification (Phase 3.5):
#   knowledge  — Arabic term lists (loaded from casualty_gender.yaml)
#   code-logic — regex construction, cover-total arithmetic, apply_* functions
# ---------------------------------------------------------------------------


def _standalone(word: str) -> re.Pattern[str]:
    """Match *word* as a standalone token, allowing optional و / ال prefixes.

    The definite article ``ال`` is explicitly permitted so forms like
    ``الشهيدة`` match. Any other preceding Arabic letter still rejects the
    match, which avoids mid-word false positives.
    """
    return re.compile(
        rf"(?<![{_ARABIC_LETTER}])(?:و)?(?:ال)?(?:{word})(?![{_ARABIC_LETTER}])"
    )


def _explicit_form_patterns(
    singular_category: str,
    dual_category: str,
) -> tuple[tuple[int, re.Pattern[str]], ...]:
    """Build count→pattern pairs from terminology categories (code-logic)."""
    patterns: list[tuple[int, re.Pattern[str]]] = []
    singular = terms_by_category(_CASUALTY_GENDER_YAML, singular_category)
    if singular:
        # One pattern per singular synonym so each can independently cover total=1.
        for term in singular:
            patterns.append(
                (1, _standalone(re.escape(normalize_arabic_text(term))))
            )
    dual = terms_by_category(_CASUALTY_GENDER_YAML, dual_category)
    if dual:
        alternation = "|".join(
            re.escape(normalize_arabic_text(term)) for term in dual
        )
        patterns.append((2, _standalone(alternation)))
    return tuple(patterns)


_EXPLICIT_FORMS: dict[str, tuple[tuple[int, re.Pattern[str]], ...]] = {
    "male_deaths": _explicit_form_patterns("male_death_singular", "male_death_dual"),
    "female_deaths": _explicit_form_patterns(
        "female_death_singular", "female_death_dual"
    ),
    "male_injuries": _explicit_form_patterns(
        "male_injury_singular", "male_injury_dual"
    ),
    "female_injuries": _explicit_form_patterns(
        "female_injury_singular", "female_injury_dual"
    ),
}

_COUNTED_PLURALS: dict[str, tuple[str, ...]] = {
    "male_deaths": tuple(
        normalize_arabic_text(term)
        for term in terms_by_category(_CASUALTY_GENDER_YAML, "male_death_plural")
    ),
    "female_deaths": tuple(
        normalize_arabic_text(term)
        for term in terms_by_category(_CASUALTY_GENDER_YAML, "female_death_plural")
    ),
    "male_injuries": tuple(
        normalize_arabic_text(term)
        for term in terms_by_category(_CASUALTY_GENDER_YAML, "male_injury_plural")
    ),
    "female_injuries": tuple(
        normalize_arabic_text(term)
        for term in terms_by_category(
            _CASUALTY_GENDER_YAML, "female_injury_plural"
        )
    ),
}


def _arabic_indic_number(value: int) -> str:
    return str(value).translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))


def _has_counted_plural(text: str, *, count: int, words: tuple[str, ...]) -> bool:
    numbers = rf"(?:{count}|{_arabic_indic_number(count)})"
    for word in words:
        if re.search(rf"{numbers}\s*{re.escape(word)}", text) or re.search(
            rf"{re.escape(word)}\s*{numbers}",
            text,
        ):
            return True
    return False


def apply_explicit_arabic_gender_evidence(
    text: str,
    casualties: ExtractionCasualties,
) -> ExtractionCasualties:
    """Do not derive demographics from grammatical casualty-word gender."""
    return casualties
    # Kept below temporarily as documentation of the superseded implementation.
    text = normalize_arabic_text(text or "")
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
                words=_COUNTED_PLURALS[female_key],
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


# knowledge: role nouns from YAML. code-logic: occupation-death regexes below.
_MALE_ROLE_NOUNS = terms_by_category(_CASUALTY_GENDER_YAML, "male_role_noun")
_FEMALE_ROLE_NOUNS = terms_by_category(_CASUALTY_GENDER_YAML, "female_role_noun")


def _role_alternation(roles: tuple[str, ...]) -> str:
    return "|".join(re.escape(role) for role in roles)


_MALE_OCCUPATION_DEATH = re.compile(
    rf"(?:شهيد|استشهاد)\s+(?:ال)?(?:{_role_alternation(_MALE_ROLE_NOUNS)})"
    rf"(?![{_ARABIC_LETTER}])"
)
_FEMALE_OCCUPATION_DEATH = re.compile(
    rf"(?:شهيده|استشهاد)\s+(?:ال)?(?:{_role_alternation(_FEMALE_ROLE_NOUNS)})"
    rf"(?![{_ARABIC_LETTER}])"
)


def apply_gendered_occupation_casualty_evidence(
    text: str,
    casualties: ExtractionCasualties,
) -> ExtractionCasualties:
    """Occupations and roles do not establish adult gender.

    ``شهيد مسعف`` / ``استشهاد مسعف`` increment ``male_deaths`` even when the
    bulletin also reports a larger mixed toll. Existing gender fields are left
    unchanged.
    """
    return casualties
    # Kept below temporarily as documentation of the superseded implementation.
    normalized = normalize_arabic_text(text or "")
    if not normalized:
        return casualties
    values = casualties.model_dump(mode="python")
    female_hits = len(_FEMALE_OCCUPATION_DEATH.findall(normalized))
    male_hits = len(_MALE_OCCUPATION_DEATH.findall(normalized))
    if female_hits and values.get("female_deaths") is None:
        values["female_deaths"] = female_hits
    if male_hits and values.get("male_deaths") is None:
        values["male_deaths"] = male_hits
    return ExtractionCasualties.model_validate(values)


def infer_singular_death_count(
    text: str,
    casualties: ExtractionCasualties,
) -> ExtractionCasualties:
    """Infer one death from unambiguous singular death nouns when no total exists."""
    values = casualties.model_dump(mode="python")
    if any(
        isinstance(values.get(key), int) and values.get(key) > 0
        for key in ("deaths", "total_deaths", "male_deaths", "female_deaths")
    ):
        return casualties
    normalized = normalize_arabic_text(text or "")
    if not normalized:
        return casualties
    male_hit = any(
        count == 1 and pattern.search(normalized)
        for count, pattern in _EXPLICIT_FORMS["male_deaths"]
    )
    female_hit = any(
        count == 1 and pattern.search(normalized)
        for count, pattern in _EXPLICIT_FORMS["female_deaths"]
    )
    if male_hit == female_hit:
        return casualties
    singular_context = re.search(
        r"(?:سقوط|ارتقاء|استشهاد|وفاه)\s+[^،,:؛]{0,30}"
        r"(?:شهيد|شهيده|قتيل|قتيله)"
        r"|(?:شهيد|شهيده|قتيل|قتيله)\s+"
        r"(?:في|جراء|اثر|نتيجه|بعد|بغاره|بقصف|بضربه)"
        r"|(?:شهيد|شهيده)\s+(?:مسعف|صحفي|اعلامي|جندي|عنصر)",
        normalized,
    )
    if singular_context is None:
        return casualties
    values["deaths"] = 1
    values["total_deaths"] = 1
    return ExtractionCasualties.model_validate(values)


def apply_casualty_gender_backstops(
    text: str,
    result: ExtractionResult,
) -> ExtractionResult:
    """Apply explicit-form and occupation gender backstops to root and sub-events."""
    if not isinstance(result, ExtractionResult):
        return result
    root = reject_unproven_demographics(text, apply_gendered_occupation_casualty_evidence(
        text,
        apply_explicit_arabic_gender_evidence(
            text,
            infer_singular_death_count(text, result.casualties),
        ),
    ))
    sub_events: list[ExtractionSubEvent] = []
    for sub_event in result.sub_events:
        span = sub_event.evidence_span or text
        sub_events.append(
            sub_event.model_copy(
                update={
                    "casualties": reject_unproven_demographics(span, apply_gendered_occupation_casualty_evidence(
                        span,
                        apply_explicit_arabic_gender_evidence(
                            span,
                            infer_singular_death_count(span, sub_event.casualties),
                        ),
                    ))
                }
            )
        )
    return result.model_copy(update={"casualties": root, "sub_events": sub_events})
