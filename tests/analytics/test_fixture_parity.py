from sqlalchemy import text

from app.analytics.services import air_breach_fact_builder as air
from app.analytics.services import refresh_service
from app.news.services.air_violations.breach_counting_service import count_breaches_by_condition
from tests.analytics.fixture_data import populate

HEADLINE = """
SELECT count(*) AS n, coalesce(sum(coalesce(i.total_deaths,0)),0) AS d, coalesce(sum(coalesce(i.total_injuries,0)),0) AS j
FROM incidents i JOIN condition_families cf ON cf.condition_id = i.condition_id
JOIN action_families af ON af.id = cf.family_id
WHERE NOT i.is_deleted AND i.verification_status IN ('verified','auto_processed') AND af.counts_in_headline
"""
PENDING = """
SELECT count(*) FROM incidents i JOIN condition_families cf ON cf.condition_id = i.condition_id
JOIN action_families af ON af.id = cf.family_id
WHERE NOT i.is_deleted AND i.verification_status <> 'rejected'
  AND (i.verification_status = 'needs_verification' OR NOT af.counts_in_headline)
"""


def test_realistic_fixture_totals_equal_direct_counts(world, db):
    populate(world)
    summary = refresh_service.full_rebuild(db)
    assert summary.failed == 0
    direct = db.execute(text(HEADLINE)).one()
    facts = db.execute(text(
        "SELECT sum(incidents), sum(deaths_total), sum(injuries_total) FROM analytics_incident_facts WHERE bucket='counted'")).one()
    assert tuple(direct) == tuple(facts) and direct.n > 250
    assert db.execute(text("SELECT sum(incidents) FROM analytics_incident_facts WHERE bucket='pending'")).scalar() == db.execute(text(PENDING)).scalar()
    # every caza is touched and national breaches equal the breach counting service
    assert db.execute(text("SELECT count(DISTINCT caza_code) FROM analytics_incident_facts")).scalar() >= 15
    expected = {k: v for k, v in count_breaches_by_condition(air.compute_all_breaches(db)).items() if v}
    assert air.fact_breach_totals(db) == expected and len(expected) == 4
