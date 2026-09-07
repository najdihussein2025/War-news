from app.llm.dtos import ExtractionCasualties, ExtractionCategory, ExtractionCategoryKey
from app.news.services.casualty_demographic_consistency import reconcile_root_demographics


def test_category_confirmed_two_male_deaths_corrects_conflicting_root_split() -> None:
    root = ExtractionCasualties(
        deaths=2,
        total_deaths=2,
        male_deaths=1,
        female_deaths=1,
    )
    categories = {
        ExtractionCategoryKey.vehicles: ExtractionCategory(
            casualties=ExtractionCasualties(male_deaths=2)
        ),
        ExtractionCategoryKey.casualty_demographics: ExtractionCategory(
            casualties=root
        ),
    }

    result = reconcile_root_demographics(root, categories)

    assert result.male_deaths == 2
    assert result.female_deaths is None


def test_partial_category_count_does_not_guess_remaining_demographics() -> None:
    root = ExtractionCasualties(deaths=3, male_deaths=1)
    categories = {
        ExtractionCategoryKey.vehicles: ExtractionCategory(
            casualties=ExtractionCasualties(male_deaths=1)
        )
    }

    assert reconcile_root_demographics(root, categories) == root


def test_children_are_excluded_from_reconciled_adult_gender_count() -> None:
    root = ExtractionCasualties(
        injuries=2,
        male_injuries=1,
        female_injuries=1,
        children_injuries=1,
    )
    categories = {
        ExtractionCategoryKey.vehicles: ExtractionCategory(
            casualties=ExtractionCasualties(male_injuries=2)
        )
    }

    result = reconcile_root_demographics(root, categories)

    assert result.male_injuries == 1
    assert result.female_injuries is None
    assert result.children_injuries == 1
