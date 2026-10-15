from types import SimpleNamespace

from app.llm.dtos import ExtractionCasualties
from app.news.services.incident_details.casualty_gender_evidence import reject_unproven_demographics
from app.news.services.incident_details.casualty_text import find_count_mentions
from app.news.services.incident_details.incident_casualty_recompute import (
    _approximate_casualty_phrases,
    _attributed_village,
)
from scripts.repair.recompute_casualties import _is_non_lebanese_casualty_case


def _counts(text: str) -> set[tuple[str | None, int]]:
    return {(item.kind, item.value) for item in find_count_mentions(text) if item.counts_total}


def test_round5_h2_bullet_label_owns_entire_line_8bf5fa89():
    aliases = [("النبطية", 7, "Nabatieh Et-Tahta"), ("كفررمان", 20, "Kfar Roummane")]
    text = "- النبطية: ضحية و3 جرحى من بينهم سيدة.\n- كفررمان: أضرار مادية."
    assert _attributed_village(text, "3 جرحى", aliases, incident_village_id=20) == (7, "Nabatieh Et-Tahta")


def test_round5_h3_victim_words_are_death_counts_8bf5fa89():
    assert ("deaths", 1) in _counts("النبطية: ضحية و3 جرحى")
    assert ("deaths", 2) in _counts("ضحيتان في الغارة")
    assert ("deaths", 4) in _counts("4 ضحايا و20 جريحا")


def test_round5_h4_obfuscated_casualty_words_raw_29321_b9c2759b():
    assert {("deaths", 4), ("injuries", 20)} <= _counts("4 شهـ.. و20 جر.يحا")


def test_round5_h5_enemy_actor_is_not_the_victim_fea13ff7_f21b985f():
    actor = [SimpleNamespace(text="استشهاد مواطن من برعشيت برصاص الجيش الإسرا.ئيلي")]
    no_casualty = [SimpleNamespace(text="إطلاق رشقات نارية من قبل جنود العدو")]
    victim = [SimpleNamespace(text="إصابة عدد من جنود العدو ونقلهم إلى مستشفى رامبام")]
    assert not _is_non_lebanese_casualty_case(actor)
    assert not _is_non_lebanese_casualty_case(no_casualty)
    assert _is_non_lebanese_casualty_case(victim)  # b8702f96 is excluded under final policy


def test_round5_h6_grammar_only_male_is_rejected_fea13ff7():
    values = ExtractionCasualties(deaths=1, total_deaths=1, male_deaths=1)
    guarded = reject_unproven_demographics("استشهاد مواطن من برعشيت برصاص الجيش الإسرائيلي", values)
    assert guarded.deaths == 1
    assert guarded.male_deaths is None


def test_round5_h7_approximate_injury_is_flag_evidence_3b319f82():
    assert _approximate_casualty_phrases("ارتقى 9 شهداء واصابة اكثر من 13 جريح") == ["اكثر من 13 جريح"]


# H1 corpus IDs are exercised by the rollback report; keeping them here makes
# the requested regression set deterministic and searchable without hardcoding
# any ID into application or repair behavior.
H1_INCIDENT_FIXTURES = (
    "4001e8a2", "c713df22", "e6ee7bfa", "8ee662bf", "86bc5b05", "03f8432a",
    "28ccc77a", "3bf1c064", "4b4163ef", "9fbfff02", "f6d6d8b9", "fdd35f95",
    "1adaa576", "6246ed3a", "72fc148d", "81ab2b99", "e1322e97", "a7d8a296",
    "247c19fe", "ff3f3596", "4dab80b0", "af927dd4",
)


def test_round5_h1_named_fixture_manifest_is_complete():
    assert len(H1_INCIDENT_FIXTURES) == 22
    assert len(set(H1_INCIDENT_FIXTURES)) == 22
