from datetime import date, time

from sqlalchemy import text

from app.analytics.services import air_breach_fact_builder as builder
from app.analytics.services import refresh_service
from app.news.services.air_violations.breach_counting_service import count_breaches_by_condition
from tests.analytics.support import BALLOON, DRONE, HELICOPTER, WARPLANE

D = date(2026, 10, 5)


def _seed(world):
    sour, saida, beirut = world.village("Sour"), world.village("Saida"), world.village("Beirut")
    # warplane: two reports within 10 min in the same mohafaza = 1 breach; one later = 2nd
    world.air(condition_id=WARPLANE, day=D, at=time(10, 0), village_ids=(sour,), commit=False)
    world.air(condition_id=WARPLANE, day=D, at=time(10, 5), village_ids=(saida,), commit=False)
    world.air(condition_id=WARPLANE, day=D, at=time(14, 0), village_ids=(sour,), commit=False)
    world.air(condition_id=WARPLANE, day=D, at=time(15, 0), caza_en="Beirut", commit=False)
    # drones: Sour is a 6-hour caza, Zahle is once per day
    world.air(condition_id=DRONE, day=D, at=time(1, 0), village_ids=(sour,), commit=False)
    world.air(condition_id=DRONE, day=D, at=time(9, 0), village_ids=(sour,), commit=False)
    world.air(condition_id=DRONE, day=D, at=time(2, 0), village_ids=(world.village("Zahle"),), commit=False)
    world.air(condition_id=DRONE, day=D, at=time(20, 0), village_ids=(world.village("Zahle"),), commit=False)
    world.air(condition_id=BALLOON, day=D, at=time(8, 0), caza_en="Aley", commit=False)
    world.air(condition_id=HELICOPTER, day=D, at=time(9, 0), village_ids=(sour, saida), commit=False)
    # no location at all -> unknown
    world.air(condition_id=WARPLANE, day=D, at=time(18, 0), commit=False)
    world.db.commit()
    return sour


def test_national_breaches_equal_count_breaches_by_condition(world, db):
    _seed(world)
    refresh_service.full_rebuild(db)
    expected = {k: v for k, v in count_breaches_by_condition(builder.compute_all_breaches(db)).items() if v}
    assert builder.fact_breach_totals(db) == expected
    assert expected[WARPLANE] >= 3


def test_warplane_rows_only_at_mohafaza_or_unknown(world, db):
    _seed(world)
    refresh_service.full_rebuild(db)
    levels = {r[0] for r in db.execute(text(
        "SELECT unit_level FROM analytics_air_breach_facts WHERE condition_id = :c"), {"c": WARPLANE})}
    assert levels <= {"mohafaza", "unknown"} and "mohafaza" in levels


def test_levels_per_condition(world, db):
    sour = _seed(world)
    refresh_service.full_rebuild(db)
    rows = db.execute(text(
        "SELECT condition_id, unit_level, area_code, mohafaza_code FROM analytics_air_breach_facts")).all()
    by = {}
    for cid, level, code, moh in rows:
        by.setdefault(cid, set()).add(level)
    assert by[DRONE] == {"caza"} and by[BALLOON] == {"caza"} and by[HELICOPTER] == {"village"}
    heli = db.execute(text("SELECT area_code FROM analytics_air_breach_facts WHERE condition_id = 38")).all()
    assert len(heli) == 2  # one breach per village named
    assert db.execute(text("SELECT admin_area_code FROM villages WHERE id=:v"), {"v": sour}).scalar() in {r[0] for r in heli}


def test_report_without_location_lands_in_unknown(world, db):
    world.air(condition_id=WARPLANE, day=D, at=time(18, 0))
    refresh_service.full_rebuild(db)
    row = db.execute(text(
        "SELECT unit_level, area_code, breaches, needs_review_breaches FROM analytics_air_breach_facts")).one()
    assert tuple(row) == ("unknown", None, 1, 1)


def test_incremental_refresh_matches_full(world, db):
    _seed(world)
    refresh_service.full_rebuild(db)
    full = db.execute(text("SELECT breach_date, condition_id, unit_level, area_code, breaches FROM analytics_air_breach_facts ORDER BY 1,2,3,4")).all()
    refresh_service.refresh_dates(db, "air", [D])
    db.commit()
    again = db.execute(text("SELECT breach_date, condition_id, unit_level, area_code, breaches FROM analytics_air_breach_facts ORDER BY 1,2,3,4")).all()
    assert full == again
