from app.news.services.summaries import invariants
from app.news.services.summaries.dtos import VillageRef
from app.news.services.summaries.gazetteer import GazetteerSnapshot
from app.news.services.summaries.headers import default_header_dictionary
from app.news.services.summaries.parser import parse_summary
from tests.summary_corpus import corpus_rows, lexicon, parse_row

LEX = lexicon()


def gaz_with_alias():
    names = {"الخيام": [VillageRef(1, "الخيام", "Marjaayoun", 1000.0, 0)],
             "المنصوري": [VillageRef(2, "المنصوري", "Sour", 2000.0, 0)],
             "بيوت السياد": [VillageRef(2, "المنصوري", "Sour", 2000.0, 0, "alias")],
             "ميفدون": [VillageRef(3, "ميفدون", "Nabatiye", 3000.0, 0)]}
    return GazetteerSnapshot(names, LEX["qualifiers"])


def parse(text):
    return parse_summary(text, gaz_with_alias(), default_header_dictionary(), LEX)


def test_alias_pair_collapses_to_one_item_without_secondary_29072():
    p = parse("التفجيرات:\nبين بيوت السياد والمنصوري")
    assert len(p.items) == 1 and p.items[0].secondary_village is None
    assert p.items[0].location_texts == ("بين بيوت السياد والمنصوري",)
    assert invariants.secondary_violations(p) == []


def test_dash_pair_with_same_village_keeps_original_phrase_28640():
    p = parse("القصف المدفعي:\nالخيام - الخيام")
    assert len(p.items) == 1 and p.items[0].secondary_village is None
    assert p.items[0].location_texts == ("الخيام - الخيام",)


def test_distinct_pair_keeps_secondary():
    p = parse("القصف المدفعي:\nبين الخيام وميفدون")
    assert p.items[0].secondary_village.name_ar == "ميفدون"


def test_standalone_line_with_same_village_pair_has_no_secondary():
    p = parse("قصف مدفعي بين بيوت السياد والمنصوري")
    assert len(p.items) == 1 and p.items[0].secondary_village is None


def test_secondary_never_equals_primary_over_every_corpus_bulletin():
    bad = {}
    for row in corpus_rows():
        found = invariants.secondary_violations(parse_row(row))
        if found:
            bad[row["message_id"]] = found[:2]
    assert not bad, f"secondary == primary: {bad}"
