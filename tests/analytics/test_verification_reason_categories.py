from app.analytics.services.verification_reason_categories import LABELS, case_sql, categorize


def test_categorize_known_pipeline_reasons():
    assert categorize("Action could not be classified from the report — confirm the incident type.") == "unclassified_action"
    assert categorize("Low-confidence condition text match requires review (text: قصف).") == "low_confidence_condition"
    assert categorize("Source metadata fallback used because no confident condition") == "low_confidence_condition"
    assert categorize("Low-confidence village match requires manual review.") == "low_confidence_village"
    assert categorize("Possible duplicate of an existing incident (similarity segment, score 1.00).") == "possible_duplicate"
    assert categorize("100% similar to an existing incident from another source") == "possible_duplicate"
    assert categorize("duplicated") == "possible_duplicate"
    assert categorize("Flare wording appears together with strike language") == "flare_and_strike"
    assert categorize("Shared casualty toll across several villages is recorded on one row") == "shared_casualty_toll"


def test_categorize_missing_and_free_text():
    assert categorize(None) == categorize("  ") == "no_reason"
    assert categorize("not related") == "other"
    assert set(LABELS) >= {"no_reason", "other", "possible_duplicate"}


def test_case_sql_escapes_like_wildcards():
    sql = case_sql("r")
    assert "'100\\% similar%'" in sql and "casualty\\_scope%" in sql
    assert sql.startswith("CASE ") and sql.endswith(" ELSE 'other' END")
