from app.llm.dtos import ExtractionCasualties
from app.news.services.incident_details.casualty_gender_evidence import apply_explicit_arabic_gender_evidence


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


def test_counted_plural_not_matching_total_does_not_fill_gender() -> None:
    original = ExtractionCasualties(deaths=4)

    assert apply_explicit_arabic_gender_evidence("3 شهداء", original) == original
