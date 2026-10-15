from app.news.services.incident_details.casualty_gender_evidence import reject_unproven_demographics
from app.news.services.incident_details.casualty_text import find_count_mentions
from app.news.services.incident_details.incident_casualty_recompute import (
    CasualtyValidationResult,
    ValidatedCasualtyClaim,
    _claim_units,
    resolved_casualty_values,
)
from app.llm.dtos import ExtractionCasualties


FIELDS = {name: None for name in (
    "deaths", "injuries", "total_deaths", "total_injuries",
    "male_d", "male_i", "female_d", "female_i", "children_d", "children_i",
)}


def _counts(text):
    return {(item.kind, item.value) for item in find_count_mentions(text) if item.counts_total}


def test_exact_main_counts_and_non_counts():
    assert {("deaths", 1), ("injuries", 2)} <= _counts("شهيد وجريحين")
    assert {("deaths", 13), ("injuries", 20)} <= _counts("ثلاثة عشر شهيدا وعشرون جريحا")
    assert ("injuries", 4) not in _counts("جريحين بينهما طفل عمره 4 سنوات")
    assert ("deaths", 11) not in _counts("11 غارة على البلدة")


def test_subset_counts_are_demographics_not_main_counts():
    mentions = find_count_mentions("11 جريحا من بينهم 4 أطفال وسيدتان ومسعف")
    assert ("injuries", 11) in {(item.kind, item.value) for item in mentions if item.counts_total}
    assert any(item.gender_or_group == "children" and item.value == 4 and not item.counts_total for item in mentions)
    assert any(item.gender_or_group == "female" and item.value == 2 for item in mentions)
    assert not any(item.gender_or_group == "male" for item in mentions)


def test_grammar_roles_names_and_child_sex_do_not_infer_adult_gender():
    values = ExtractionCasualties(deaths=1, injuries=2, male_deaths=1, male_injuries=2, female_deaths=1)
    guarded = reject_unproven_demographics("شهيد وجريحين ومسعف وطفلة", values)
    assert guarded.male_deaths is None and guarded.male_injuries is None
    assert guarded.female_deaths is None


def test_totals_equal_main_and_explicit_people_can_supply_missing_main():
    claim = ValidatedCasualtyClaim(1, "raw_messages", 7, "Village", {**FIELDS, "children_d": 1, "female_d": 1}, {"children_d": "طفل", "female_d": "سيدة"})
    result = CasualtyValidationResult((claim,), (1,), 1, 1, 0, ("Village",))
    values, conflict = resolved_casualty_values(result, 7)
    assert conflict is None
    assert values["deaths"] == values["total_deaths"] == 2


def test_haddatha_field_contract():
    claim = ValidatedCasualtyClaim(1, "raw_messages", 21, "Haddatha", {**FIELDS, "injuries": 2, "children_i": 1}, {"injuries": "إلى وقع جريحين بينهما طفل عمره 4 سنوات", "children_i": "إلى وقع جريحين بينهما طفل عمره 4 سنوات"})
    result = CasualtyValidationResult((claim,), (1,), 1, 1, 0, ("Haddatha",))
    values, conflict = resolved_casualty_values(result, 21)
    assert conflict is None
    assert values == {**FIELDS, "injuries": 2, "total_injuries": 2, "children_i": 1}


def test_non_lebanese_victim_policy_is_exclusionary():
    from types import SimpleNamespace
    from scripts.repair.recompute_casualties import _is_non_lebanese_casualty_case
    assert _is_non_lebanese_casualty_case([SimpleNamespace(text="إصابة 5 من جنود العدو ونقلهم إلى مستشفى رامبام")])


def _unit_values(text):
    return [values for _claim_id, _claim_text, values, _listed in _claim_units(text)]


def test_k1_mayfadoun_main_count_and_subset_stay_distinct():
    values = _unit_values("ميفدون قضاء النبطية: 4 جرحى من بينهم 2 سيدات")[0]
    assert values["injuries"] == 4 and values["female_i"] == 2


def test_k1_one_line_keeps_death_and_injury_claims():
    values = _unit_values("النبطية: ضحية و3 جرحى من بينهم سيدة")
    assert any(item["deaths"] == 1 for item in values)
    injury = next(item for item in values if item["injuries"] == 3)
    assert injury["female_i"] == 1


def test_k1_kfarroummane_subset_sum_excludes_main_count():
    values = _unit_values("11 جريحا من بينهم 4 أطفال وسيدتان ومسعف")[0]
    assert values["injuries"] == 11
    assert values["children_i"] == 4 and values["female_i"] == 2
    assert sum(values[key] or 0 for key in ("male_i", "female_i", "children_i")) == 6


def test_k1_death_subsets_remain_on_death_claim():
    values = _unit_values("8 شهداء من بينهم طفل وسيدتان")[0]
    assert values["deaths"] == 8
    assert values["children_d"] == 1 and values["female_d"] == 2


def test_k1_two_main_counts_own_only_their_following_subsets():
    values = _unit_values(
        "8 شهداء من بينهم طفل وسيدتان، و11 جريحا من بينهم 4 أطفال وسيدتان ومسعف"
    )
    death = next(item for item in values if item["deaths"] == 8)
    injury = next(item for item in values if item["injuries"] == 11)
    assert death["children_d"] == 1 and death["female_d"] == 2
    assert death["children_i"] is None
    assert injury["children_i"] == 4 and injury["female_i"] == 2
    assert injury["children_d"] is None
