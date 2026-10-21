from datetime import date

from sqlalchemy import text

from app.analytics.services import refresh_service

D1 = date(2026, 10, 1)


def test_dirty_queue_rebuilds_then_clears(world, db):
    world.incident(village_id=world.village("Sour"), condition="Bombs", day=D1, deaths=1)
    summary = refresh_service.process_dirty_queue(db, 60)
    assert (summary.processed, summary.succeeded, summary.failed) == (1, 1, 0)
    assert db.execute(text("SELECT count(*) FROM analytics_dirty_dates")).scalar() == 0
    assert db.execute(text("SELECT sum(incidents) FROM analytics_incident_facts")).scalar() == 1


def test_mark_that_moves_during_rebuild_is_kept(world, db, engine):
    world.incident(village_id=world.village("Sour"), condition="Bombs", day=D1)
    read = db.execute(text("SELECT marked_at FROM analytics_dirty_dates")).scalar()
    db.rollback()
    with engine.begin() as conn:  # a concurrent edit re-marks the date
        conn.execute(text("UPDATE incidents SET total_deaths = 4"))
    refresh_service.refresh_dates(db, "incident", [D1])
    db.execute(refresh_service._DELETE_MARKS, {"kinds": ["incident"], "dates": [D1], "marks": [read]})
    db.commit()
    assert db.execute(text("SELECT count(*) FROM analytics_dirty_dates")).scalar() == 1


def test_batch_size_limits_work(world, db):
    for day in range(1, 6):
        world.incident(village_id=world.village("Sour"), condition="Bombs", day=date(2026, 10, day))
    summary = refresh_service.process_dirty_queue(db, 2)
    assert summary.processed == 2
    assert db.execute(text("SELECT count(*) FROM analytics_dirty_dates")).scalar() == 3
