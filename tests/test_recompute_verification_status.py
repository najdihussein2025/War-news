from scripts.recompute_verification_status import (
    _preserved_governance_reasons,
    _reason_bucket,
    _rule_bucket,
)


def test_soft_condition_reason_is_not_preserved() -> None:
    assert _preserved_governance_reasons(
        "Low-confidence condition text match requires review (text: قصف)."
    ) == []


def test_low_confidence_village_reason_is_not_preserved() -> None:
    """Phase 4 policy: this is now a quality flag, never carried over."""
    assert _preserved_governance_reasons(
        "Low-confidence village match requires manual review."
    ) == []


def test_village_dedup_duplicate_text_is_not_preserved_verbatim() -> None:
    """decide_verification recomputes rule 2 fresh from
    duplicate_similarity_score; the old free-text reason is not carried over."""
    assert _preserved_governance_reasons(
        "Possible duplicate of an existing incident — flagged during fast-path matching."
    ) == []


def test_governance_reasons_are_preserved_but_cross_source_duplicate_is_recomputed() -> None:
    cross = "Possible cross-source duplicate segment; human confirmation required"
    merge = "Possible duplicate — casualty count conflict detected during merge"
    revision = "Unconfirmed story revision would lower deaths; review before applying"
    assert _preserved_governance_reasons(cross) == []
    assert _preserved_governance_reasons(merge) == [merge]
    assert _preserved_governance_reasons(revision) == [revision]


def test_reason_buckets_collapse_expected_legacy_reasons() -> None:
    assert _reason_bucket(None) == "[NULL/empty]"
    assert _reason_bucket("Unsupported casualty_scope=x") == "Unsupported casualty scope"
    assert _reason_bucket(
        "Low-confidence condition text match requires review (text: غارة)."
    ) == "Low-confidence condition"


def test_rule_bucket_classifies_reasons_into_rules_1_2_3() -> None:
    assert _rule_bucket(None) == "[none]"
    assert _rule_bucket("Casualties are mentioned without an exact number.") == (
        "rule 1: casualty attribution"
    )
    assert _rule_bucket(
        "92% similar to an existing incident from another source — confirm "
        "whether this is a duplicate."
    ) == "rule 2: likely duplicate"
    assert _rule_bucket(
        "Possible duplicate — casualty count conflict detected during merge."
    ) == "rule 3: governance safeguard"

