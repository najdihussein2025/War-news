"""Analytics v2, Part 1: regression tests for the accuracy fixes."""
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.analytics.dtos.filters import Filters
from app.analytics.repositories import analytics_repository as repo
from app.analytics.services import refresh_service
from app.core.config import settings
from tests.analytics.test_api import client, fake_cache  # noqa: F401  (fixtures)

D1 = date(2026, 10, 1)
Q = "date_from=2026-10-01&date_to=2026-10-07"


def _raw(db, source_id: int, day: date, n: int) -> None:
    for i in range(n):
        db.execute(text("""
            INSERT INTO raw_messages (source_id, raw_text, raw_payload, message_datetime)
            VALUES (:s, 'x', '{}'::jsonb, :t)"""),
            {"s": source_id, "t": datetime(day.year, day.month, day.day, 9, i % 60, tzinfo=timezone.utc)})


@pytest.fixture()
def ranked(world, db):
    """Kfar-Tibnit-like case: the busiest village must rank first even if its name sorts last."""
    sour = [world.village("Sour", i) for i in range(3)]
    for _ in range(5):
        world.incident(village_id=sour[2], condition="Bombs", day=D1, commit=False)
    for _ in range(2):
        world.incident(village_id=sour[0], condition="Bombs", day=D1, commit=False)
        world.incident(village_id=sour[1], condition="Bombs", day=D1, commit=False)
    db.commit()
    refresh_service.full_rebuild(db)
    return sour


def test_rankings_default_to_metric_desc_with_fixed_rank(client, ranked, db):  # noqa: F811
    body = client.get(f"/api/analytics/rankings?{Q}&level=village").json()
    values = [r["value"] for r in body["rows"]]
    assert values == sorted(values, reverse=True)
    assert values[0] == 5
    assert [r["rank"] for r in body["rows"]] == list(range(1, len(values) + 1))
    tied = [r["name_en"] for r in body["rows"] if r["value"] == 2]
    assert tied == sorted(tied)  # ties: name


def test_pending_chip_equals_card_and_definition(client, world, db):  # noqa: F811
    sour, zahle = world.village("Sour"), world.village("Zahle")
    world.incident(village_id=sour, condition="Bombs", day=D1, status="needs_verification", commit=False)
    world.incident(village_id=sour, condition="Unclassified / Needs Review", day=D1, commit=False)
    world.incident(village_id=zahle, condition="Air Activity - Needs Verification", day=D1, commit=False)
    world.incident(village_id=zahle, condition="Bombs", day=D1, status="needs_verification", deleted=True, commit=False)
    world.incident(village_id=zahle, condition="Bombs", day=D1, status="rejected", commit=False)
    world.incident(village_id=zahle, condition="Bombs", day=D1)  # counted
    world.incident(village_id=zahle, condition="Bombs", day=date(2026, 9, 1), status="needs_verification")  # outside
    refresh_service.full_rebuild(db)
    kpis = client.get(f"/api/analytics/kpis?{Q}").json()
    quality = client.get(f"/api/analytics/quality?{Q}").json()
    direct = db.execute(text("""
        SELECT count(*) FROM incidents i
        LEFT JOIN condition_families cf ON cf.condition_id = i.condition_id
        LEFT JOIN action_families af ON af.id = cf.family_id
        WHERE NOT i.is_deleted AND i.verification_status <> 'rejected'
          AND i.event_date BETWEEN '2026-10-01' AND '2026-10-07'
          AND (i.verification_status = 'needs_verification' OR af.counts_in_headline IS NOT TRUE)""")).scalar_one()
    assert kpis["pending_review"] == quality["pending_review"] == direct == 3
    meta = client.get("/api/analytics/meta").json()
    assert meta["pending_review"]["incidents"] == 4  # all time, same function


def test_casualty_completeness(client, world, db):  # noqa: F811
    sour = world.village("Sour")
    world.incident(village_id=sour, condition="Bombs", day=D1, deaths=1, casualty_status="exact", commit=False)
    world.incident(village_id=sour, condition="Bombs", day=D1, casualty_status="none_mentioned", commit=False)
    world.incident(village_id=sour, condition="Bombs", day=D1, commit=False)
    world.incident(village_id=sour, condition="Bombs", day=D1, commit=False)
    db.commit()
    refresh_service.full_rebuild(db)
    body = client.get(f"/api/analytics/kpis?{Q}").json()["casualty_completeness"]
    assert body == {"incidents": 4, "with_status": 2, "pct": 50.0}
    facts = db.execute(text("SELECT sum(casualty_known) FROM analytics_incident_facts")).scalar_one()
    direct = db.execute(text("SELECT count(*) FROM incidents WHERE casualty_status IS NOT NULL")).scalar_one()
    assert facts == direct


def test_coverage_marks_none_and_low_days(client, world, db):  # noqa: F811
    db.execute(text("TRUNCATE raw_messages RESTART IDENTITY CASCADE"))
    start = D1 - timedelta(days=28)
    day = start
    while day < D1:
        _raw(db, world.source_id, day, 10)
        day += timedelta(days=1)
    _raw(db, world.source_id, D1, 10)
    _raw(db, world.source_id, D1 + timedelta(days=1), 2)  # low: 2 < 0.3 * 10
    # D1 + 2 has nothing at all
    for i in range(3, 7):
        _raw(db, world.source_id, D1 + timedelta(days=i), 9)
    db.commit()
    body = client.get(f"/api/analytics/coverage?{Q}").json()
    status = {d["date"]: d["status"] for d in body["days"]}
    assert status["2026-10-01"] == "ok"
    assert status["2026-10-02"] == "low"
    assert status["2026-10-03"] == "none"
    assert status["2026-10-04"] == "ok"
    assert body["low_days"] == 1 and body["no_coverage_days"] == 1
    assert body["days"][0]["sources"] == {"test source": 10}
    timeline = client.get(f"/api/analytics/timeline?{Q}").json()
    assert timeline["coverage"]["gap_dates"] == ["2026-10-02", "2026-10-03"]
    assert {f["status"] for f in timeline["coverage"]["flagged"]} == {"low", "none"}


def test_coverage_before_first_message_is_unknown(db, world):
    db.execute(text("TRUNCATE raw_messages RESTART IDENTITY CASCADE"))
    _raw(db, world.source_id, D1 + timedelta(days=3), 5)
    db.commit()
    days = repo.coverage_days(db, D1, D1 + timedelta(days=4), 0.3)
    assert [d["status"] for d in days] == ["unknown", "unknown", "unknown", "ok", "none"]


def test_peak_day_on_low_coverage_is_flagged(client, world, db):  # noqa: F811
    db.execute(text("TRUNCATE raw_messages RESTART IDENTITY CASCADE"))
    _raw(db, world.source_id, D1 - timedelta(days=1), 10)
    db.commit()
    world.incident(village_id=world.village("Sour"), condition="Bombs", day=D1)
    refresh_service.full_rebuild(db)
    peaks = client.get(f"/api/analytics/peaks?{Q}").json()
    assert peaks["incidents"]["day"]["low_coverage_days"] == 1  # D1 had no message at all


def test_geo_anomaly_lists_villages_outside_the_conflict_zone(client, world, db, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "analytics_geo_anomaly_min_incidents", 3)
    batroun, sour, baabda = world.village("Batroun"), world.village("Sour"), world.village("Baabda")
    for _ in range(4):
        world.incident(village_id=batroun, condition="Bombs", day=D1, commit=False)
        world.incident(village_id=sour, condition="Bombs", day=D1, commit=False)
        world.incident(village_id=baabda, condition="Bombs", day=D1, commit=False)
    world.incident(village_id=batroun, condition="Bombs", day=D1, status="needs_verification", commit=False)
    db.commit()
    refresh_service.full_rebuild(db)
    rows = client.get(f"/api/analytics/quality?{Q}").json()["geo_anomalies"]["rows"]
    assert len(rows) == 1
    assert rows[0]["caza_en"] == "El Batroun" and rows[0]["incidents"] == 5
    flt = Filters(date_from=D1, date_to=D1)
    assert repo.geo_anomalies(db, flt, 10, frozenset(), frozenset()) == []
