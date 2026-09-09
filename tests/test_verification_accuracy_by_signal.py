from __future__ import annotations

from scripts.review.verification_accuracy_by_signal import classify_signal_bucket


def test_bucket_hard_signal_wins_over_confidence_signal() -> None:
    result = _match_result(village_status="matched_low_confidence")

    classification = classify_signal_bucket(
        result,
        duplicate_flag=True,
        duplicate_level="medium",
        duplicate_similarity_score=0.64,
    )

    assert classification.bucket == "hard_signal"
    assert "duplicate_flag" in classification.signals
    assert any(signal.startswith("target_village:") for signal in classification.signals)


def test_bucket_auto_processed_for_one_target_village_signal() -> None:
    classification = classify_signal_bucket(
        _match_result(village_status="matched_low_confidence")
    )

    assert classification.bucket == "auto_processed_now"


def test_bucket_auto_processed_for_condition_and_target_village() -> None:
    classification = classify_signal_bucket(
        _match_result(
            village_status="matched_low_confidence",
            condition_status="matched_low_confidence",
        )
    )

    assert classification.bucket == "auto_processed_now"


def test_bucket_auto_processed_now_for_origin_low_confidence_only() -> None:
    result = _match_result(village_status="matched_low_confidence")
    result["village_matches"][0]["village_role"] = "origin"

    classification = classify_signal_bucket(result)

    assert classification.bucket == "auto_processed_now"


def test_bucket_auto_processed_for_relevance_review() -> None:
    classification = classify_signal_bucket(
        _match_result(),
        relevance_needs_review=True,
    )

    assert classification.bucket == "auto_processed_now"
    assert "relevance_needs_review" in classification.signals


def test_bucket_auto_processed_for_existing_casualty_reason() -> None:
    classification = classify_signal_bucket(
        _match_result(),
        verification_reason="Casualty count may be incomplete - needs review.",
    )

    assert classification.bucket == "auto_processed_now"


def _match_result(
    *,
    village_status: str = "matched",
    condition_status: str = "matched",
) -> dict:
    return {
        "village_matches": [
            {
                "raw_village_text": "Mansouri",
                "matched_village_id": 976,
                "village_confidence": 0.55
                if village_status == "matched_low_confidence"
                else 1.0,
                "village_match_status": village_status,
                "village_review_required": village_status != "matched",
                "village_role": "target",
            }
        ],
        "any_village_low_confidence": village_status == "matched_low_confidence",
        "raw_condition_text": "Shelling",
        "condition_confidence": 0.55
        if condition_status == "matched_low_confidence"
        else 1.0,
        "matched_condition_id": 5,
        "condition_match_status": condition_status,
        "condition_review_required": condition_status != "matched",
    }
