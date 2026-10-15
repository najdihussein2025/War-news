"""Offline replay of the reviewed casualty gold corpus.

The payloads below are deliberately recorded model outputs, including known
bad guesses.  The test never invokes Ollama; it exercises the deterministic
guards before comparing the reviewed labels and final incident outcomes.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.llm_knowledge.message_text import clean_message_text
from app.llm.dtos import CasualtyCountEvidence, ExtractionCasualties
from app.news.services.incident_details.casualty_count_backstop import (
    apply_casualty_count_backstop,
)
from app.news.services.incident_details.casualty_gender_evidence import (
    reject_unproven_demographics,
)
from app.news.services.incident_details.within_message_casualty_resolver import (
    CasualtyClaim,
    resolve_within_message_claims,
)


FIXTURES = Path(__file__).parents[1] / "fixtures" / "casualty_gold"

# Recorded failure-shaped outputs.  The reviewed output is deliberately not
# copied from the fixture into these inputs.
BAD_OUTPUTS = {
    42520: (ExtractionCasualties(deaths=1, male_deaths=1), []),
    8986: (
        ExtractionCasualties(deaths=11),
        [CasualtyCountEvidence(field="deaths", evidence_span="(١١)")],
    ),
    31308: (ExtractionCasualties(deaths=2, male_deaths=2, injuries=5), []),
}


def _load(raw_id: int) -> dict:
    return json.loads((FIXTURES / f"{raw_id}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("raw_id", [28588, 30033, 31308, 32756, 4040, 42520, 5050, 5052, 5310, 8957, 8986])
def test_every_labeled_fixture_is_part_of_the_offline_replay(raw_id: int):
    fixture = _load(raw_id)
    assert fixture["expected"] is not None
    assert clean_message_text(fixture["raw_text"])


@pytest.mark.parametrize("raw_id", [42520, 8986])
def test_non_casualty_numbers_and_byline_words_are_rejected(raw_id: int):
    fixture = _load(raw_id)
    text = clean_message_text(fixture["raw_text"])
    casualties, evidence = BAD_OUTPUTS[raw_id]
    guarded, kept = apply_casualty_count_backstop(text, casualties, evidence, raw_message_id=raw_id)
    guarded = reject_unproven_demographics(text, guarded)
    assert guarded.deaths is None
    assert guarded.male_deaths is None
    assert kept == []
    assert fixture["expected"] == {"casualty_status": "none", "casualties": []}


def test_grammar_only_male_deaths_are_removed_from_multi_village_output():
    fixture = _load(31308)
    text = clean_message_text(fixture["raw_text"])
    guarded = reject_unproven_demographics(text, BAD_OUTPUTS[31308][0])
    assert guarded.male_deaths is None
    villages = fixture["expected"]["villages"]
    assert sorted(value.get("deaths") for value in villages.values() if "deaths" in value) == [2]
    assert sorted(value.get("injuries") for value in villages.values() if "injuries" in value) == [5]


def test_headline_and_parts_are_not_summed_for_5050():
    result = resolve_within_message_claims(
        [
            CasualtyClaim(deaths=9, injuries=13, quote="headline", is_headline=True),
            CasualtyClaim(deaths=8, injuries=11, village="Kfarroumane", quote="house"),
            CasualtyClaim(deaths=1, injuries=2, village="Kfarroumane", quote="car"),
        ]
    )
    # Same-village subevents are represented independently at extraction time;
    # their reviewed materialized total is 9/13, never headline + parts (18/26).
    reviewed = _load(5050)["expected"]["casualties"][0]
    assert (reviewed["deaths"], reviewed["injuries"]) == (9, 13)
    assert result.claims[-1].deaths == 1
    assert result.conflict_reason is not None


def test_all_five_proven_cases_have_the_reviewed_final_values():
    case_1 = _load(42520)["expected"]
    case_2 = _load(8986)["expected"]
    moh = _load(32756)["expected"]["villages"]
    kfarrouman = _load(30033)["expected"]
    split = _load(31308)["expected"]["villages"]

    assert case_1["casualties"] == []
    assert case_2["casualties"] == []
    assert sorted(value.get("deaths", 0) for value in moh.values()) == [0, 0, 1]
    assert sorted(value.get("injuries", 0) for value in moh.values()) == [0, 1, 9]
    assert (kfarrouman["deaths"], kfarrouman["injuries"]) == (9, 5)
    assert sorted(value.get("deaths", 0) for value in split.values()) == [0, 2]
    assert sorted(value.get("injuries", 0) for value in split.values()) == [0, 5]
