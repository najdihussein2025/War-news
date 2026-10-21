from datetime import date, timedelta

import pytest
from sqlalchemy import text

from app.analytics.services import refresh_service
from app.analytics.services.archive_service import ArchiveError, archive_incidents

D1, D2, D3 = date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3)

# Headline predicate, evaluated directly on the incidents table (not through facts).
DIRECT = """
SELECT {group}, count(*) AS n, coalesce(sum(coalesce(i.total_deaths,0)),0) AS deaths,
       coalesce(sum(coalesce(i.total_injuries,0)),0) AS injuries
FROM incidents i
JOIN villages v ON v.id = i.village_id
JOIN condition_families cf ON cf.condition_id = i.condition_id
JOIN action_families af ON af.id = cf.family_id
WHERE NOT i.is_deleted AND i.verification_status IN ('verified','auto_processed')
  AND af.counts_in_headline
GROUP BY {group} ORDER BY 1
"""
FACTS = """
SELECT {group}, sum(incidents) AS n, sum(deaths_total) AS deaths, sum(injuries_total) AS injuries
FROM analytics_incident_facts WHERE bucket = 'counted' AND source = 'live'
GROUP BY {group} ORDER BY 1
"""


def _populate(world):
    cazas = ["Sour", "Saida", "Zahle", "Baalbek", "Akkar"]
    n = 0
    for caza in cazas:
        for k in range(3):
            vid = world.village(caza, k)
            for day in (D1, D2, D3):
                for cond, status, deleted in (
                    ("Artillery Shelling", "auto_processed", False),
                    ("Bombs", "verified", False),
                    ("Bombs", "needs_verification", False),
                    ("Tank Fire", "rejected", False),
                    ("Shooting", "auto_processed", True),
                    ("Unclassified / Needs Review", "auto_processed", False),
                ):
                    n += 1
                    world.incident(village_id=vid, condition=cond, day=day, status=status, deleted=deleted,
                                   deaths=n % 3, injuries=n % 4, commit=False)
    world.db.commit()


@pytest.mark.parametrize("group", ["i.event_date", "v.admin_area_code"])
def test_parity_by_date_and_village(world, db, group):
    _populate(world)
    refresh_service.refresh_incident_dates(db, None)
    db.commit()
    fact_group = {"i.event_date": "event_date", "v.admin_area_code": "admin_village_code"}[group]
    direct = [tuple(r) for r in db.execute(text(DIRECT.format(group=group)))]
    facts = [tuple(r) for r in db.execute(text(FACTS.format(group=fact_group)))]
    assert direct == facts
    assert sum(r[1] for r in facts) > 0


@pytest.mark.parametrize("level", ["caza_code", "mohafaza_code"])
def test_parity_by_caza_and_mohafaza(world, db, level):
    _populate(world)
    refresh_service.refresh_incident_dates(db, None)
    db.commit()
    direct = [tuple(r) for r in db.execute(text(
        DIRECT.format(group=f"a.{level}").replace(
            "JOIN villages v ON v.id = i.village_id",
            "JOIN villages v ON v.id = i.village_id JOIN admin_areas a ON a.code = v.admin_area_code"))) ]
    facts = [tuple(r) for r in db.execute(text(FACTS.format(group=level)))]
    assert direct == facts


def test_pending_bucket_holds_needs_verification_and_unclassified(world, db):
    vid = world.village("Sour")
    world.incident(village_id=vid, condition="Bombs", day=D1, status="needs_verification", deaths=2)
    world.incident(village_id=vid, condition="Unclassified / Needs Review", day=D1, deaths=1)
    world.incident(village_id=vid, condition="Air Activity - Needs Verification", day=D1)
    world.incident(village_id=vid, condition="Bombs", day=D1, status="rejected", deaths=9)
    world.incident(village_id=vid, condition="Bombs", day=D1, deleted=True, deaths=9)
    refresh_service.refresh_incident_dates(db, None)
    db.commit()
    rows = dict(db.execute(text(
        "SELECT bucket, sum(incidents) FROM analytics_incident_facts GROUP BY bucket")).all())
    assert rows == {"pending": 3}


def test_legacy_deaths_column_is_never_used(world, db):
    world.incident(village_id=world.village("Sour"), condition="Bombs", day=D1, deaths=None, legacy_deaths=50)
    refresh_service.refresh_incident_dates(db, None)
    db.commit()
    assert db.execute(text("SELECT sum(deaths_total) FROM analytics_incident_facts")).scalar() == 0


def test_unspecified_casualties_with_partial_demographics(world, db):
    vid = world.village("Sour")
    world.incident(village_id=vid, condition="Bombs", day=D1, deaths=5, injuries=4,
                   male_d=2, female_d=1, children_d=1, male_i=1)
    world.incident(village_id=vid, condition="Bombs", day=D1, deaths=1, male_d=3)  # inconsistent: clamp at 0
    refresh_service.refresh_incident_dates(db, None)
    db.commit()
    row = db.execute(text("""
        SELECT sum(deaths_total), sum(deaths_male), sum(deaths_female), sum(deaths_children),
               sum(deaths_unspecified), sum(injuries_total), sum(injuries_male), sum(injuries_unspecified)
        FROM analytics_incident_facts""")).one()
    assert tuple(row) == (6, 5, 1, 1, 1, 4, 1, 3)


def test_shared_toll_counted_once(world, db):
    owner, member = world.village("Sour", 0), world.village("Sour", 1)
    world.incident(village_id=owner, condition="Bombs", day=D1, deaths=4, injuries=6, casualty_status="aggregate_only")
    world.incident(village_id=member, condition="Bombs", day=D1)  # member keeps NULL casualties
    refresh_service.refresh_incident_dates(db, None)
    db.commit()
    row = db.execute(text(
        "SELECT sum(incidents), sum(deaths_total), sum(injuries_total), sum(aggregate_only_incidents) "
        "FROM analytics_incident_facts")).one()
    assert tuple(row) == (2, 4, 6, 1)


def test_null_totals_count_as_zero_and_village_without_code_keeps_id(world, db):
    vid = world.village("Sour")
    code = db.execute(text("SELECT admin_area_code FROM villages WHERE id = :v"), {"v": vid}).scalar()
    db.execute(text("UPDATE villages SET admin_area_code = NULL WHERE id = :v"), {"v": vid})
    try:
        world.incident(village_id=vid, condition="Bombs", day=D1)
        refresh_service.refresh_incident_dates(db, None)
        db.commit()
        row = db.execute(text(
            "SELECT village_id, admin_village_code, caza_code, deaths_total FROM analytics_incident_facts")).one()
        assert tuple(row) == (vid, None, None, 0)
    finally:
        db.execute(text("UPDATE villages SET admin_area_code = :c WHERE id = :v"), {"c": code, "v": vid})
        db.commit()


def test_incident_in_archive_is_excluded_from_live_facts(world, db):
    vid = world.village("Sour")
    world.incident(village_id=vid, condition="Bombs", day=D1, deaths=2)
    archive_incidents(db, "b1")
    db.commit()
    refresh_service.refresh_incident_dates(db, None)
    refresh_service.build_archive_facts(db, "b1")
    rows = db.execute(text("SELECT source, sum(incidents) FROM analytics_incident_facts GROUP BY source")).all()
    assert dict(rows) == {"archive": 1}


def test_archive_facts_are_frozen_and_not_rebuilt_twice(world, db):
    vid = world.village("Sour")
    world.incident(village_id=vid, condition="Bombs", day=D1, deaths=2)
    archive_incidents(db, "b1")
    db.commit()
    refresh_service.build_archive_facts(db, "b1")
    with pytest.raises(refresh_service.ArchiveFactsError):
        refresh_service.build_archive_facts(db, "b1")
    db.rollback()
    before = db.execute(text("SELECT * FROM analytics_incident_facts WHERE source='archive'")).all()
    # reset: live table emptied, then live refreshes of the archived date must leave archive rows alone
    db.execute(text("SET LOCAL analytics.skip_dirty_marks = 'on'"))
    db.execute(text("DELETE FROM incidents"))
    db.commit()
    refresh_service.refresh_incident_dates(db, [D1])
    refresh_service.refresh_incident_dates(db, None)
    db.commit()
    after = db.execute(text("SELECT * FROM analytics_incident_facts WHERE source='archive'")).all()
    assert before == after and len(after) == 1


def test_archive_refuses_existing_batch_and_keeps_deleted_rows(world, db):
    vid = world.village("Sour")
    world.incident(village_id=vid, condition="Bombs", day=D1, deleted=True)
    world.incident(village_id=vid, condition="Bombs", day=D1, status="rejected")
    result = archive_incidents(db, "b1")
    db.commit()
    assert result["rows"] == 2
    with pytest.raises(ArchiveError):
        archive_incidents(db, "b1")


def test_unmapped_condition_falls_back_to_pending_unclassified(world, db):
    bombs = world.condition["Bombs"]
    family_id = db.execute(text("SELECT family_id FROM condition_families WHERE condition_id = :c"), {"c": bombs}).scalar()
    db.execute(text("DELETE FROM condition_families WHERE condition_id = :c"), {"c": bombs})
    db.commit()
    try:
        world.incident(village_id=world.village("Sour"), condition="Bombs", day=D1)
        refresh_service.refresh_incident_dates(db, None)
        db.commit()
        assert db.execute(text("SELECT bucket FROM analytics_incident_facts")).scalar() == "pending"
    finally:
        db.rollback()
        db.execute(text("INSERT INTO condition_families (condition_id, family_id) VALUES (:c, :f)"), {"c": bombs, "f": family_id})
        db.commit()
