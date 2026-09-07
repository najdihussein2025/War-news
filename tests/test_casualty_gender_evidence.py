from app.llm.dtos import ExtractionCasualties
from app.news.services.incident_details.casualty_gender_evidence import (
    _EXPLICIT_FORMS,
    apply_explicit_arabic_gender_evidence,
)


def test_explicit_masculine_singular_fills_death_and_injury() -> None:
    result = apply_explicit_arabic_gender_evidence(
        "شهيد في ياطر وجريح عولج ميدانيا",
        ExtractionCasualties(deaths=1, injuries=1),
    )

    assert result.male_deaths == 1
    assert result.male_injuries == 1
    assert result.female_deaths is None
    assert result.female_injuries is None


def test_explicit_feminine_singular_fills_death_and_injury() -> None:
    result = apply_explicit_arabic_gender_evidence(
        "شهيدة وجريحة",
        ExtractionCasualties(deaths=1, injuries=1),
    )

    assert result.female_deaths == 1
    assert result.female_injuries == 1
    assert result.male_deaths is None
    assert result.male_injuries is None


def test_definite_article_shahida_forms_match_and_fill_female() -> None:
    cases = (
        "شهيدة إسراء",
        "الشهيدة إسراء",
        "استشهاد الشهيدة إسراء",
    )
    for text in cases:
        assert _EXPLICIT_FORMS["female_deaths"][0][1].search(text), text
        result = apply_explicit_arabic_gender_evidence(
            text,
            ExtractionCasualties(deaths=1),
        )
        assert result.female_deaths == 1, text
        assert result.male_deaths is None, text


def test_definite_article_musaba_fills_female_injury() -> None:
    for text in ("مصابة", "المصابة"):
        assert _EXPLICIT_FORMS["female_injuries"][1][1].search(text), text
        result = apply_explicit_arabic_gender_evidence(
            text,
            ExtractionCasualties(injuries=1),
        )
        assert result.female_injuries == 1, text
        assert result.male_injuries is None, text


def test_musab_singular_fills_male_injury() -> None:
    result = apply_explicit_arabic_gender_evidence(
        "مصاب في الغارة",
        ExtractionCasualties(injuries=1),
    )

    assert result.male_injuries == 1
    assert result.female_injuries is None


def test_gender_is_not_inferred_when_explicit_count_does_not_cover_total() -> None:
    original = ExtractionCasualties(deaths=3, injuries=3)

    assert apply_explicit_arabic_gender_evidence("شهيد وجريح", original) == original


def test_mixed_gender_words_do_not_override_model() -> None:
    original = ExtractionCasualties(deaths=1)

    assert apply_explicit_arabic_gender_evidence("شهيد وشهيدة", original) == original


def test_counted_masculine_plural_does_not_guess_all_are_male() -> None:
    result = apply_explicit_arabic_gender_evidence(
        "الصحة اللبنانية: 3 شهداء وجريحان بينهما طفل",
        ExtractionCasualties(deaths=3, injuries=2, children_injuries=1),
    )

    assert result.male_deaths is None
    assert result.male_injuries == 1
    assert result.children_injuries == 1


def test_arabic_indic_counted_feminine_plural_is_filled() -> None:
    result = apply_explicit_arabic_gender_evidence(
        "٣ شهيدات و٤ جريحات",
        ExtractionCasualties(deaths=3, injuries=4),
    )

    assert result.female_deaths == 3
    assert result.female_injuries == 4


def test_counted_musabat_plural_fills_female_injuries() -> None:
    result = apply_explicit_arabic_gender_evidence(
        "4 مصابات في الغارة",
        ExtractionCasualties(injuries=4),
    )

    assert result.female_injuries == 4
    assert result.male_injuries is None


def test_counted_plural_not_matching_total_does_not_fill_gender() -> None:
    original = ExtractionCasualties(deaths=4)

    assert apply_explicit_arabic_gender_evidence("3 شهداء", original) == original


def test_null_gender_is_never_defaulted_to_male() -> None:
    """No gender marker and null demographics must stay null (never invent male)."""
    original = ExtractionCasualties(deaths=1, injuries=2)

    result = apply_explicit_arabic_gender_evidence(
        "سقوط ضحايا في غارة على البلدة",
        original,
    )

    assert result == original
    assert result.male_deaths is None
    assert result.female_deaths is None
    assert result.male_injuries is None
    assert result.female_injuries is None
