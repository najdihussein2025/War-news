"""Phase 4 verification policy: only casualty attribution (rule 1) and a
likely duplicate (rule 2) may send an incident to needs_verification.
Everything else is a quality flag, never a review reason.
"""

from app.news.services.materialization.verification_signals import (
    VerificationSignals,
    decide_duplicate_outcome,
    decide_verification,
)


def _match(*village_matches, **extra):
    return {"village_matches": list(village_matches), **extra}


def _vm(village_id, **extra):
    return {"matched_village_id": village_id, "village_role": "target", **extra}


# --- Rule 1: casualty attribution --------------------------------------------


def test_rule1_vague_casualty_count_goes_to_review():
    extraction = {"casualty_status": "count_missing"}
    signals = VerificationSignals(extraction_result=extraction)

    status, reasons, flags, payload = decide_verification(None, signals)

    assert status == "needs_verification"
    assert reasons == ["Casualties are mentioned without an exact number."]
    assert flags == []


def test_rule1_aggregate_toll_across_two_villages_goes_to_review():
    extraction = {
        "casualty_scope": "bulletin_aggregate",
        "casualties": {"deaths": 3},
    }
    match = _match(_vm(1), _vm(2))
    signals = VerificationSignals(match_result=match, extraction_result=extraction)

    status, reasons, flags, payload = decide_verification(None, signals)

    assert status == "needs_verification"
    assert "no per-location breakdown" in reasons[0]


def test_rule1_per_village_breakdown_does_not_go_to_review():
    extraction = {
        "casualty_scope": "bulletin_aggregate",
        "casualties": {"deaths": 3},
        "village_roles": [{"role": "target", "deaths": 3}],
    }
    match = _match(_vm(1), _vm(2))
    signals = VerificationSignals(match_result=match, extraction_result=extraction)

    status, reasons, flags, payload = decide_verification(None, signals)

    assert status == "auto_processed"
    assert reasons == []


# --- Rule 2: likely duplicate -------------------------------------------------


def test_rule2_similarity_in_review_band_goes_to_review():
    assert decide_duplicate_outcome(0.90, same_village=True, same_condition=True, same_casualties=True, event_gap_hours=1) == "review"

    signals = VerificationSignals(duplicate_similarity_score=0.90)
    status, reasons, flags, payload = decide_verification(None, signals)
    assert status == "needs_verification"
    assert "90% similar" in reasons[0]


def test_rule2_autolink_band_with_matching_attributes_and_within_window_auto_links_no_review():
    outcome = decide_duplicate_outcome(
        0.99,
        same_village=True,
        same_condition=True,
        same_casualties=True,
        event_gap_hours=2,
    )
    assert outcome == "auto_link"

    signals = VerificationSignals(
        duplicate_similarity_score=0.99,
        duplicate_same_village=True,
        duplicate_same_condition=True,
        duplicate_same_casualties=True,
        duplicate_event_gap_hours=2,
    )
    status, reasons, flags, payload = decide_verification(None, signals)
    assert status == "auto_processed"
    assert reasons == []


def test_rule2_autolink_band_with_mismatched_village_still_goes_to_review():
    outcome = decide_duplicate_outcome(
        0.99,
        same_village=False,
        same_condition=True,
        same_casualties=True,
        event_gap_hours=1,
    )
    assert outcome == "review"


def test_rule2_below_review_threshold_is_not_a_duplicate_signal():
    outcome = decide_duplicate_outcome(0.70, same_village=True, same_condition=True, same_casualties=True, event_gap_hours=1)
    assert outcome == "none"

    signals = VerificationSignals(duplicate_similarity_score=0.70)
    status, reasons, flags, payload = decide_verification(None, signals)
    assert status == "auto_processed"
    assert reasons == []


# --- Everything else becomes a quality flag, never a review reason ----------


def test_low_confidence_village_is_a_quality_flag_not_a_review_reason():
    match = _match({**_vm(1), "village_match_status": "matched_low_confidence", "village_review_required": True})
    signals = VerificationSignals(match_result=match, village_id=1)

    status, reasons, flags, payload = decide_verification(None, signals)

    assert status == "auto_processed"
    assert reasons == []
    assert {"flag": "low_confidence_village"} in flags


def test_ungrounded_condition_is_a_quality_flag_not_a_review_reason():
    match = _match(
        {**_vm(1), "condition_review_reason": "No usable text-grounded or source-metadata condition candidate."}
    )
    signals = VerificationSignals(match_result=match, village_id=1)

    status, reasons, flags, payload = decide_verification(None, signals)

    assert status == "auto_processed"
    assert reasons == []
    assert {"flag": "unresolved_condition"} in flags


def test_tier2_retry_cap_is_a_quality_flag_not_a_review_reason():
    signals = VerificationSignals(tier2_retry_count=3, tier2_retry_limit=3)

    status, reasons, flags, payload = decide_verification(None, signals)

    assert status == "auto_processed"
    assert reasons == []
    assert {"flag": "tier2_retry_cap", "retry_count": 3} in flags


def test_multi_village_no_subevents_is_a_quality_flag_not_a_review_reason():
    signals = VerificationSignals(multi_village_no_subevents=True)

    status, reasons, flags, payload = decide_verification(None, signals)

    assert status == "auto_processed"
    assert {"flag": "multi_village_no_subevents"} in flags


def test_flare_wording_is_a_quality_flag_not_a_review_reason():
    signals = VerificationSignals(flare_wording_detail="قنابل مضيئة وحارقة")

    status, reasons, flags, payload = decide_verification(None, signals)

    assert status == "auto_processed"
    assert {"flag": "flare_wording", "detail": "قنابل مضيئة وحارقة"} in flags


def test_unresolved_village_with_casualties_is_a_quality_flag_not_a_review_reason():
    match = _match(_vm(1), {**_vm(None), "deaths": 2})
    signals = VerificationSignals(match_result=match, village_id=1)

    status, reasons, flags, payload = decide_verification(None, signals)

    assert status == "auto_processed"
    assert reasons == []
    assert any(f["flag"] == "unresolved_village_with_casualties" for f in flags)


# --- Rule 3: governance safeguards pass through untouched -------------------


def test_governance_hard_reason_forces_review_independent_of_rules_1_and_2():
    signals = VerificationSignals(
        governance_hard_reasons=("Possible duplicate — casualty count conflict detected during merge.",)
    )

    status, reasons, flags, payload = decide_verification(None, signals)

    assert status == "needs_verification"
    assert reasons == ["Possible duplicate — casualty count conflict detected during merge."]

