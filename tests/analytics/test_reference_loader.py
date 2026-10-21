from sqlalchemy import text

from app.analytics.constants import CAZA_NAME_TO_CODE, MOHAFAZA_NAME_TO_CODE
from app.news.services.air_violations.caza_alias_resolver import canonicalize_caza


def test_every_condition_is_mapped(db):
    conditions = db.execute(text("SELECT count(*) FROM conditions")).scalar()
    mapped = db.execute(text("SELECT count(*) FROM condition_families")).scalar()
    assert conditions == mapped and conditions > 40


def test_unclassified_conditions_belong_to_non_headline_family(db):
    rows = db.execute(text("""
        SELECT c.action_en, af.code, af.counts_in_headline FROM conditions c
        JOIN condition_families cf ON cf.condition_id = c.id JOIN action_families af ON af.id = cf.family_id
        WHERE c.id IN (45, 87, 46)""")).all()
    got = {r[0]: (r[1], r[2]) for r in rows}
    assert got["Air Activity - Needs Verification"] == ("unclassified", False)
    assert got["Unclassified / Needs Review"] == ("unclassified", False)
    assert got["Bombs"] == ("airstrikes", True)


def test_area_counts_and_caza_mapping_26_to_26(db):
    levels = dict(db.execute(text("SELECT level, count(*) FROM admin_areas GROUP BY 1")).all())
    assert levels == {"mohafaza": 8, "caza": 26, "village": 1610}
    pairs = db.execute(text("""
        SELECT v.caza_en, a.caza_code, a.mohafaza_code, v.mohafaza_en FROM villages v
        JOIN admin_areas a ON a.code = v.admin_area_code GROUP BY 1,2,3,4""")).all()
    by_caza: dict[str, set[str]] = {}
    for caza_en, caza_code, moh_code, moh_en in pairs:
        by_caza.setdefault(canonicalize_caza(caza_en), set()).add(caza_code)
        assert MOHAFAZA_NAME_TO_CODE[moh_en] == moh_code
    assert len(by_caza) == 26 and all(len(v) == 1 for v in by_caza.values())
    for name, codes in by_caza.items():
        assert CAZA_NAME_TO_CODE[name] == next(iter(codes)), name
    assert len({CAZA_NAME_TO_CODE[n] for n in by_caza}) == 26


def test_village_links_are_by_code_and_idempotent(db):
    linked = db.execute(text("SELECT count(*) FROM villages WHERE admin_area_code IS NOT NULL")).scalar()
    mismatched = db.execute(text("SELECT count(*) FROM villages WHERE admin_area_code <> acs_code::text")).scalar()
    assert mismatched == 0 and linked >= 1543
