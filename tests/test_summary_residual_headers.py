from dataclasses import replace

from app.news.services.summaries import invariants
from app.news.services.summaries.dtos import VillageRef
from app.news.services.summaries.gazetteer import GazetteerSnapshot
from app.news.services.summaries.headers import default_header_dictionary
from app.news.services.summaries.parser import parse_summary
from tests.summary_corpus import corpus_rows, gazetteer, lexicon, parse_row

LEX = lexicon()


def gaz():
    return GazetteerSnapshot({n: [VillageRef(i, n, "Nabatiye", i * 1000.0, 0)] for i, n in enumerate(["الخيام", "حداثا", "شقرا"], 1)}, LEX["qualifiers"])


def parse(text):
    return parse_summary(text, gaz(), default_header_dictionary(), LEX)


def test_residual_carries_the_header_of_its_own_section_not_the_last_one():
    p = parse("القصف المدفعي المعادي:\nصريين\nالخيام\nالقنابل الصوتيه:\nحداثا")
    rows = {(x.kind, x.text): x.section_header for x in p.residual}
    assert rows[("unresolved_place", "صريين")] == "القصف المدفعي المعادي"


def test_same_text_under_two_headers_gets_each_headers_label():
    p = parse("القصف المدفعي:\nمكان غامض طويل جدا\nالتفجيرات:\nمكان غامض طويل جدا")
    assert [(x.kind, x.section_header) for x in p.residual] == [("out_of_scope", "القصف المدفعي"), ("out_of_scope", "التفجيرات")]


def test_offsets_point_at_the_residual_text():
    text = "القصف المدفعي:\nالخيام\nصريين\nالتفجيرات:\nحداثا"
    p = parse(text)
    row = next(x for x in p.residual if x.text == "صريين")
    assert text[row.offsets[0]:row.offsets[1]] == "صريين"


def test_prose_section_residual_is_recorded_with_its_header():
    p = parse("اعتداءات اخرى:\nدبابة «ميركافا» استهدفت مدينة الخيام")
    assert [(x.kind, x.section_header) for x in p.residual] == [("out_of_scope", "اعتداءات اخري")]


def test_residual_header_checker_catches_a_stale_label():
    text = "القصف المدفعي:\nصريين\nالتفجيرات:\nحداثا"
    g, h = gaz(), default_header_dictionary()
    result = parse_summary(text, g, h, LEX)
    assert invariants.residual_header_violations(text, result, g, h) == []
    stale = replace(result, residual=tuple(replace(x, section_header="التفجيرات") for x in result.residual))
    assert invariants.residual_header_violations(text, stale, g, h)


def test_residual_header_over_every_corpus_bulletin():
    g, h = gazetteer(), default_header_dictionary()
    bad = {}
    for row in corpus_rows():
        found = invariants.residual_header_violations(row["text"], parse_row(row, g, h), g, h)
        if found:
            bad[row["message_id"]] = found[:2]
    assert not bad, f"residual header violated: {bad}"


def test_named_corpus_bulletins_label_each_residual_with_its_own_header():
    rows = {r["message_id"]: r for r in corpus_rows()}
    labelled = {m: {(x.kind, x.text): x.section_header for x in parse_row(rows[m]).residual} for m in (28017, 28640, 31010)}
    # 28017: صريين sits under the artillery header, not the last section (sound bombs).
    assert labelled[28017][("unresolved_place", "صريين")] == "القصف المدفعي المعادي"
    # 28640: عيتا الجبل belongs to the machine-gun combing section at the end.
    assert labelled[28640][("unresolved_place", "عيتا الجبل")].endswith("تمشيط بالاسلحهالرشاشه")
    assert labelled[28640][("unresolved_place", "حي الرويس-النبطيه")].startswith("-الغارات التي نفذها الطيران المسير")
    # 31010: the unknown place line is its own barrier; the rows below it carry its label.
    assert labelled[31010][("place_under_unresolved_header", "حداثا.")] == "دوحه كفرمان"
    assert labelled[31010][("out_of_scope", "سلسله غارات استهدفت منطقه علي الطاهر")] == "غارات جويه"
