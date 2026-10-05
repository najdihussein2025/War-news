import pytest

from app.news.services.materialization.incident_materialization_service import (
    _initial_verification_status,
)
from app.news.services.matching.matching_service import MatchingService
from app.news.services.matching.condition_aliases import CONDITION_ALIASES


def test_generic_attack_aliases_are_exact_only_and_bare_drone_is_not_an_alias() -> None:
    aliases = {
        alias.text: (action_ar, alias.exact_only)
        for action_ar, values in CONDITION_ALIASES.items()
        for alias in values
    }
    for term in ("قصف", "غارة", "غارات", "غارة جوية", "استهداف", "استهدف"):
        assert aliases[term] == ("قصف وغارات", True)
    for term in ("مسيرة", "مسيّرة", "طيران مسير"):
        assert term not in aliases


@pytest.mark.parametrize("condition_id", [3, 4])
def test_bare_drone_word_does_not_match_failure_or_suicide(condition_id: int) -> None:
    assert not MatchingService._condition_match_allowed(condition_id, "مسيرة")


def test_drone_failure_and_suicide_require_distinguishing_words() -> None:
    assert MatchingService._condition_match_allowed(3, "سقوط مسيرة")
    assert MatchingService._condition_match_allowed(4, "مسيرة مفخخة")


def test_low_condition_confidence_with_confident_village_is_auto_processed() -> None:
    match = {
        "condition_review_required": True,
        "condition_review_reason": (
            "Low-confidence condition text match requires review (text: قصف)."
        ),
        "village_matches": [
            {
                "matched_village_id": 101,
                "village_role": "target",
                "village_match_status": "matched",
                "village_review_required": False,
                "condition_review_required": True,
                "condition_review_reason": (
                    "Low-confidence condition text match requires review (text: قصف)."
                ),
            }
        ],
    }
    assert _initial_verification_status(match, village_id=101) == "auto_processed"


def test_no_usable_condition_still_requires_review() -> None:
    match = {
        "condition_review_required": True,
        "condition_review_reason": (
            "No usable text-grounded or source-metadata condition candidate."
        ),
        "village_matches": [
            {
                "matched_village_id": 101,
                "village_role": "target",
                "village_match_status": "matched",
                "village_review_required": False,
                "condition_review_required": True,
                "condition_review_reason": (
                    "No usable text-grounded or source-metadata condition candidate."
                ),
            }
        ],
    }
    assert _initial_verification_status(match, village_id=101) == "needs_verification"
