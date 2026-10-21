from datetime import date, time

from sqlalchemy import text

from tests.analytics.support import WARPLANE

D1, D2 = date(2026, 10, 1), date(2026, 10, 2)


def _dirty(db, kind="incident"):
    db.rollback()
    return sorted(r[0] for r in db.execute(
        text("SELECT event_date FROM analytics_dirty_dates WHERE kind = :k"), {"k": kind}))


def _clear(db):
    db.execute(text("DELETE FROM analytics_dirty_dates"))
    db.commit()


def test_insert_marks_date(world, db):
    world.incident(village_id=world.village("Sour"), condition="Bombs", day=D1)
    assert _dirty(db) == [D1]


def test_update_date_marks_old_and_new(world, db):
    iid = world.incident(village_id=world.village("Sour"), condition="Bombs", day=D1)
    _clear(db)
    db.execute(text("UPDATE incidents SET event_date = :d WHERE id = :i"), {"d": D2, "i": iid})
    db.commit()
    assert _dirty(db) == [D1, D2]


def test_relevant_columns_mark_and_irrelevant_do_not(world, db):
    iid = world.incident(village_id=world.village("Sour"), condition="Bombs", day=D1)
    _clear(db)
    db.execute(text("UPDATE incidents SET khabar = 'edited', note = 'x', version = version + 1 WHERE id = :i"), {"i": iid})
    db.commit()
    assert _dirty(db) == []
    for column_set in ("total_deaths = 3", "verification_status = 'verified'", "is_deleted = true, deleted_reason = 'admin'"):
        db.execute(text(f"UPDATE incidents SET {column_set} WHERE id = :i"), {"i": iid})
        db.commit()
        assert _dirty(db) == [D1], column_set
        _clear(db)


def test_delete_marks_date(world, db):
    iid = world.incident(village_id=world.village("Sour"), condition="Bombs", day=D1)
    _clear(db)
    db.execute(text("DELETE FROM incidents WHERE id = :i"), {"i": iid})
    db.commit()
    assert _dirty(db) == [D1]


def test_details_demographic_change_marks_other_detail_columns_do_not(world, db):
    iid = world.incident(village_id=world.village("Sour"), condition="Bombs", day=D1, male_d=1)
    _clear(db)
    db.execute(text("UPDATE incident_details SET la = true WHERE incident_id = :i"), {"i": iid})
    db.commit()
    assert _dirty(db) == []
    db.execute(text("UPDATE incident_details SET male_d = 2 WHERE incident_id = :i"), {"i": iid})
    db.commit()
    assert _dirty(db) == [D1]


def test_skip_guard_marks_nothing(world, db):
    iid = world.incident(village_id=world.village("Sour"), condition="Bombs", day=D1)
    _clear(db)
    db.execute(text("SET LOCAL analytics.skip_dirty_marks = 'on'"))
    db.execute(text("UPDATE incidents SET total_deaths = 9 WHERE id = :i"), {"i": iid})
    db.execute(text("DELETE FROM incidents WHERE id = :i"), {"i": iid})
    db.commit()
    assert _dirty(db) == []


def test_bulletin_group_and_members_mark_incident_date(world, db):
    owner = world.incident(village_id=world.village("Sour"), condition="Bombs", day=D1, casualty_status="aggregate_only", deaths=2)
    db.execute(text("INSERT INTO sources (type,name) SELECT 'telegram','x' WHERE false"))
    raw = db.execute(text(
        "INSERT INTO raw_messages (source_id, external_message_id, raw_text, raw_payload, status) "
        "SELECT id, 'ext1', 't', '{}', 'pending' FROM sources LIMIT 1 RETURNING id")).scalar()
    group = db.execute(text(
        "INSERT INTO bulletin_casualty_groups (raw_message_id, village_ids, casualty_scope, owner_incident_id, breakdown_status) "
        "VALUES (:r, '[]', 'bulletin_aggregate', :o, 'pending') RETURNING id"), {"r": raw, "o": owner}).scalar()
    db.commit()
    _clear(db)
    db.execute(text("UPDATE bulletin_casualty_groups SET total_deaths = 5 WHERE id = :g"), {"g": group})
    db.commit()
    assert _dirty(db) == [D1]
    _clear(db)
    db.execute(text(
        "INSERT INTO bulletin_casualty_group_members (group_id, village_id, ordinal, incident_id) "
        "VALUES (:g, :v, 0, :i)"), {"g": group, "v": world.village("Sour"), "i": owner})
    db.commit()
    assert _dirty(db) == [D1]


def test_air_marks_day_before_day_after(world, db):
    air_id = world.air(condition_id=WARPLANE, day=D1, at=time(10, 0), village_ids=(world.village("Sour"),))
    assert _dirty(db, "air") == [date(2026, 9, 30), D1, D2]
    _clear(db)
    db.execute(text("UPDATE air_violations SET khabar = 'edited' WHERE id = :a"), {"a": air_id})
    db.commit()
    assert _dirty(db, "air") == []
    db.execute(text("INSERT INTO air_violation_locations (air_violation_id, village_id) VALUES (:a, :v)"),
               {"a": air_id, "v": world.village("Saida")})
    db.commit()
    assert _dirty(db, "air") == [date(2026, 9, 30), D1, D2]
