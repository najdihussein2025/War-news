from __future__ import annotations

import json
from pathlib import Path

from app.news.services.casualty_transition_backstop import (
    detect_casualty_transition_backstop,
)


CASES_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "phase2-extraction-live-check"
    / "casualty_transition_eval_cases.json"
)


def _eval_cases() -> list[dict]:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def test_backstop_catches_named_transition_failures() -> None:
    cases = {case["case_id"]: case for case in _eval_cases()}

    for case_id in (
        "real_transition_restate_mifdoun_425",
        "supp_transition_death_only_houla",
        "real_ambiguous_habboush_2698",
    ):
        result = detect_casualty_transition_backstop(cases[case_id]["raw_text"])
        assert result.plausible is True, case_id


def test_backstop_avoids_false_positives_on_additive_cases() -> None:
    cases = {case["case_id"]: case for case in _eval_cases()}

    for case_id in (
        "real_additive_arabsalim_2413",
        "real_additive_roueiss_3077",
        "real_additive_shebaa_791",
    ):
        result = detect_casualty_transition_backstop(cases[case_id]["raw_text"])
        assert result.plausible is False, case_id
