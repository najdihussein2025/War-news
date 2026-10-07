from datetime import date

import pytest

from app.news.services.summaries import invariants, parser
from app.news.services.summaries.dtos import VillageRef
from app.news.services.summaries.gazetteer import GazetteerSnapshot
from app.news.services.summaries.headers import default_header_dictionary
from app.news.services.summaries.parser import parse_summary
from tests.summary_corpus import corpus_rows, gazetteer, lexicon, parse_row

LEX = lexicon()
NAMES = ["الخيام", "المنصوري", "ميفدون", "حداثا", "شقرا", "علي الطاهر"]


def gaz():
    return GazetteerSnapshot({n: [VillageRef(i, n, "Nabatiye", i * 1000.0, 0)] for i, n in enumerate(NAMES, 1)}, LEX["qualifiers"])


def parse(text):
    return parse_summary(text, gaz(), default_header_dictionary(), LEX)


def pairs(result):
    return {(i.condition_id, i.primary_village.name_ar) for i in result.items}


def barrier_rows(result):
    return [(x.text, x.section_header) for x in result.residual if x.kind == "place_under_unresolved_header"]


# --- vocabulary (28640, 31010, 29072) -------------------------------------

def test_burning_properties_header_28640():
    p = parse("التفجيرات:\nالخيام\n-احراق المنازل:\nحداثا")
    assert pairs(p) == {(21, "الخيام"), (27, "حداثا")}


@pytest.mark.parametrize("header", ["احراق المنازل", "احراق منازل", "احراق ممتلكات", "يضرم النيران"])
def test_burning_variants(header):
    assert pairs(parse(f"{header}:\nحداثا")) == {(27, "حداثا")}


@pytest.mark.parametrize("header", ["● قصف بالقذائف الفسفورية", "القذائف الفسفورية:"])
def test_phosphorus_header_31010(header):
    p = parse(f"قصف مدفعي:\nالمنصوري\n{header}\nعلي الطاهر")
    assert pairs(p) == {(5, "المنصوري"), (7, "علي الطاهر")}


def test_singular_sound_and_light_bombs():
    assert pairs(parse("قنبلة صوتية:\nالخيام\nقنبلة مضيئة:\nحداثا")) == {(10, "الخيام"), (9, "حداثا")}


def test_plus_phosphorus_suffix_adds_to_header_condition_29072():
    p = parse("القصف المدفعي:\nعلي الطاهر+فوسفوري\nحداثا")
    assert pairs(p) == {(5, "علي الطاهر"), (7, "علي الطاهر"), (5, "حداثا")}
    assert {i.condition_source for i in p.items if i.condition_id == 7} == {"header+inline"}


def test_full_inline_action_replaces_header_condition():
    p = parse("التفجيرات:\nالخيام مدفعي+فوسفوري")
    assert pairs(p) == {(5, "الخيام"), (7, "الخيام")}


# --- the barrier, as a general rule ---------------------------------------

def test_unknown_colon_header_is_not_inherited_over():
    p = parse("التفجيرات:\nالخيام\n-فعل غامض:\nحداثا\nشقرا")
    assert pairs(p) == {(21, "الخيام")}
    assert barrier_rows(p) == [("حداثا", "فعل غامض"), ("شقرا", "فعل غامض")]


def test_unknown_header_with_inline_place_is_a_barrier():
    p = parse("التفجيرات:\nالخيام\n-فعل غامض: حداثا\nشقرا")
    assert pairs(p) == {(21, "الخيام")}
    assert {t for t, _ in barrier_rows(p)} >= {"شقرا"}


@pytest.mark.parametrize("bullet", ["●", "○", "🟠", "🔵", "🏴", "-"])
def test_section_bullet_short_line_without_place_is_a_barrier(bullet):
    p = parse(f"التفجيرات:\nالخيام\n{bullet} كلام غريب جدا\nحداثا")
    assert pairs(p) == {(21, "الخيام")}
    assert barrier_rows(p) == [("حداثا", "كلام غريب جدا")]


def test_plain_place_bullet_is_not_a_barrier():
    p = parse("التفجيرات:\n• الخيام\n• مكان مجهول\n• حداثا")
    assert pairs(p) == {(21, "الخيام"), (21, "حداثا")} and not barrier_rows(p)


def test_action_core_line_without_place_is_a_barrier():
    p = parse("التفجيرات:\nالخيام\nغارات علي منطقه مجهوله\nحداثا")
    assert pairs(p) == {(21, "الخيام")}
    assert barrier_rows(p) == [("حداثا", "غارات علي منطقه مجهوله")]


def test_line_naming_its_own_action_takes_nothing_from_an_unresolved_header():
    p = parse("التفجيرات:\nالخيام\n-فعل غامض:\nقصف مدفعي حداثا\nشقرا")
    assert pairs(p) == {(21, "الخيام"), (5, "حداثا")}
    assert barrier_rows(p) == [("شقرا", "فعل غامض")]


def test_timed_event_lines_are_not_barriers():
    p = parse("القصف المدفعي:\nالساعة 5:20 صباحا قصف مدفعي ثقيل مع تحرك اليات\nحداثا")
    assert pairs(p) == {(5, "حداثا")} and not barrier_rows(p)


def test_glued_place_tokens_are_still_places():
    text = "- الساعة 6:30 صباحا تفجير جديد في بلده المنصوري-وسط البلده\n- كفرشوبا(قذائف دخانيه)\n- الساعة 7:30 صباحا قصف مدفعي علي حداثا"
    p = parse_summary(text, gaz(), default_header_dictionary(), LEX, date(2026, 9, 1))
    assert {(i.condition_id, i.primary_village.name_ar) for i in p.items} >= {(21, "المنصوري"), (5, "حداثا")}
    assert not barrier_rows(p)


def test_lines_above_the_first_header_are_parsed_not_dropped():
    p = parse("قصف مدفعي معاد استهدف الخيام\nالتفجيرات:\nحداثا")
    assert pairs(p) == {(5, "الخيام"), (21, "حداثا")}


def test_blocking_nothing_adds_no_unresolved_header_row():
    p = parse("صفحه الاعلامي الشهيد علي شعيب:\nالتفجيرات:\nالخيام")
    assert pairs(p) == {(21, "الخيام")} and not p.residual and p.disposition == "complete"


# --- provenance invariant -------------------------------------------------

def test_provenance_checker_catches_inheritance_across_a_barrier(monkeypatch):
    """Negative control: with the barrier disabled the checker must report a violation."""
    text = "التفجيرات:\nالخيام\n-فعل غامض:\nحداثا"
    g, h = gaz(), default_header_dictionary()
    assert invariants.header_provenance_violations(text, parse(text), g, h) == []
    monkeypatch.setattr(parser, "is_header_like", lambda *a, **k: False)
    broken = parse_summary(text, g, h, LEX)
    assert (21, "حداثا") in pairs(broken)  # the silent error the barrier prevents
    monkeypatch.undo()
    assert invariants.header_provenance_violations(text, broken, g, h)


def test_header_provenance_over_every_corpus_bulletin():
    g, h = gazetteer(), default_header_dictionary()
    bad = {}
    for row in corpus_rows():
        found = invariants.header_provenance_violations(row["text"], parse_row(row, g, h), g, h)
        if found:
            bad[row["message_id"]] = found[:2]
    assert not bad, f"header provenance violated: {bad}"


def test_named_regressions_in_the_corpus():
    rows = {r["message_id"]: r for r in corpus_rows()}
    got = {m: {(i.condition_id, i.primary_village.name_ar) for i in parse_row(rows[m]).items} for m in (28640, 31010, 29072)}
    assert {(27, "أرنون"), (27, "طلوسة")} <= got[28640] and not {(21, "أرنون"), (21, "طلوسة")} & got[28640]
    assert (7, "علي الطاهر") in got[31010] and (5, "علي الطاهر") in got[31010]
    assert {(5, "علي الطاهر"), (7, "علي الطاهر")} <= got[29072]


def test_signature_above_the_first_header_is_not_review_work_but_a_bare_place_is():
    p = parse("صفحه الاعلامي الشهيد علي شعيب\nالتفجيرات:\nالخيام")
    assert pairs(p) == {(21, "الخيام")} and not p.residual and p.disposition == "complete"
    q = parse("حداثا\nالتفجيرات:\nالخيام")
    assert [(x.kind, x.text) for x in q.residual] == [("unresolved_place", "حداثا")]
