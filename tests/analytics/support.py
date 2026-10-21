"""Scratch-database helpers for analytics tests.

DB tests run only when ANALYTICS_TEST_DATABASE_URL points at an isolated ``*_test``
database that is migrated to head: the fixtures TRUNCATE incidents, air violations,
conditions and villages. Never point it at a database holding data you need.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import date, time
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.news.models  # noqa: F401
import app.sources.models  # noqa: F401
from tests.db_guard import assert_scratch_truncation_allowed

ROOT = Path(__file__).resolve().parents[2]
UNCLASSIFIED_AR = "غير مصنف / بحاجة إلى مراجعة"
AIR_NEEDS_VERIFICATION_AR = "نشاط جوي بحاجة إلى التحقق"

# Live-like condition ids: 2..44 follow Data/Conditions.json order (Bombs and
# Vehicle Movement are not there), 45 = Air Activity - Needs Verification,
# 46 = Bombs, 87 = Unclassified / Needs Review. Air ids are 34/35/36/38 as in prod.
WARPLANE, DRONE, HELICOPTER, BALLOON = 35, 36, 38, 34


def _condition_rows() -> list[tuple[int, str, str]]:
    data = json.loads((ROOT / "Data/Conditions.json").read_text(encoding="utf-8"))
    rows: list[tuple[int, str, str]] = []
    for position, item in enumerate(data, start=1):
        if item["action_en"] in {"Bombs", "Vehicle Movement"}:
            continue
        rows.append((position, item["action_en"], item["action_ar"]))
    bombs = next(i for i in data if i["action_en"] == "Bombs")
    rows.append((45, "Air Activity - Needs Verification", AIR_NEEDS_VERIFICATION_AR))
    rows.append((46, bombs["action_en"], bombs["action_ar"]))
    rows.append((87, "Unclassified / Needs Review", UNCLASSIFIED_AR))
    return rows


def analytics_engine():
    url = os.environ.get("ANALYTICS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("ANALYTICS_TEST_DATABASE_URL (an isolated *_test database) is required")
    assert_scratch_truncation_allowed(url)
    engine = create_engine(url)
    with engine.connect() as conn:
        present = conn.execute(text("SELECT to_regclass('analytics_incident_facts')")).scalar()
    if present is None:
        pytest.skip("test database is not migrated to the analytics revision (alembic upgrade head)")
    return engine


def seed_reference(engine) -> dict:
    """Reset reference tables and load conditions, villages, admin areas, families."""
    from app.analytics.services.reference_loader import apply_reference, plan_reference

    with engine.begin() as conn:
        conn.execute(text(
            "TRUNCATE incident_details, incidents, air_violation_locations, air_violations, "
            "incidents_archive, analytics_incident_facts, analytics_air_breach_facts, "
            "analytics_dirty_dates, condition_families, action_families, conditions, villages, "
            "admin_areas, sources RESTART IDENTITY CASCADE"
        ))
        for cid, en, ar in _condition_rows():
            conn.execute(
                text("INSERT INTO conditions (id, action_en, action_ar) VALUES (:i, :e, :a)"),
                {"i": cid, "e": en, "a": ar},
            )
        villages = json.loads((ROOT / "Data/Villages.json").read_text(encoding="utf-8"))
        seen: set[int] = set()
        for v in villages:
            if v["acs_code"] in seen:
                continue
            seen.add(v["acs_code"])
            conn.execute(text(
                "INSERT INTO villages (acs_code, acs_name, ref_name_en, ref_name_ar, caza_en, caza_ar, "
                "mohafaza_en, mohafaza_ar) VALUES (:acs_code, :acs_name, :ref_name_en, :ref_name_ar, "
                ":caza_en, :caza_ar, :mohafaza_en, :mohafaza_ar)"
            ), {k: v.get(k) for k in (
                "acs_code", "acs_name", "ref_name_en", "ref_name_ar", "caza_en", "caza_ar",
                "mohafaza_en", "mohafaza_ar")})
        conn.execute(text("INSERT INTO sources (type, name) VALUES ('telegram', 'test source')"))
        conn.execute(text("SELECT setval(pg_get_serial_sequence('conditions','id'), 200)"))
    with Session(engine) as db:
        plan = plan_reference(db, ROOT / "frontend/public/geo", ROOT / "Data/analytics/action_families.json")
        apply_reference(db, plan)
        db.commit()
    return {"plan": plan}


def clean_world(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(
            "TRUNCATE incident_details, incidents, air_violation_locations, air_violations, "
            "incidents_archive, analytics_incident_facts, analytics_air_breach_facts, "
            "analytics_dirty_dates RESTART IDENTITY CASCADE"
        ))


class World:
    """Convenience builders over a Session."""

    def __init__(self, db: Session):
        self.db = db
        self.condition = {
            row.action_en: row.id for row in db.execute(text("SELECT id, action_en FROM conditions"))
        }
        self.source_id = db.execute(text("SELECT id FROM sources LIMIT 1")).scalar_one()

    def village(self, caza_en: str, nth: int = 0) -> int:
        rows = self.db.execute(
            text("SELECT id FROM villages WHERE caza_en = :c AND admin_area_code IS NOT NULL ORDER BY id"),
            {"c": caza_en},
        ).all()
        return int(rows[nth].id)

    def incident(
        self, *, village_id: int, condition: str | int, day: date, status: str = "auto_processed",
        deleted: bool = False, deaths: int | None = None, injuries: int | None = None,
        casualty_status: str | None = None, male_d=None, female_d=None, children_d=None,
        male_i=None, female_i=None, children_i=None, legacy_deaths: int | None = None,
        commit: bool = True,
    ) -> uuid.UUID:
        condition_id = condition if isinstance(condition, int) else self.condition[condition]
        incident_id = uuid.uuid4()
        self.db.execute(text("""
            INSERT INTO incidents (id, village_id, condition_id, source_id, event_date, event_time, khabar,
                                   verification_status, is_deleted, deleted_reason, total_deaths,
                                   total_injuries, deaths, casualty_status)
            VALUES (:id, :v, :c, :s, :d, '10:00', :k, :st, :del, :reason, :td, :ti, :ld, :cs)
        """), {
            "id": incident_id, "v": village_id, "c": condition_id, "s": self.source_id, "d": day,
            "k": f"khabar {incident_id}", "st": status, "del": deleted,
            "reason": "admin" if deleted else None, "td": deaths, "ti": injuries,
            "ld": legacy_deaths, "cs": casualty_status,
        })
        if any(v is not None for v in (male_d, female_d, children_d, male_i, female_i, children_i)):
            self.db.execute(text("""
                INSERT INTO incident_details (incident_id, male_d, female_d, children_d, male_i, female_i, children_i)
                VALUES (:id, :a, :b, :c, :d, :e, :f)
            """), {"id": incident_id, "a": male_d, "b": female_d, "c": children_d,
                   "d": male_i, "e": female_i, "f": children_i})
        if commit:
            self.db.commit()
        return incident_id

    def air(self, *, condition_id: int, day: date, at: time | None = None, caza_en: str | None = None,
            village_ids: tuple[int, ...] = (), commit: bool = True) -> int:
        air_id = self.db.execute(text("""
            INSERT INTO air_violations (condition_id, source_id, caza_en, event_date, event_time, khabar)
            VALUES (:c, :s, :caza, :d, :t, 'air khabar') RETURNING id
        """), {"c": condition_id, "s": self.source_id, "caza": caza_en, "d": day, "t": at}).scalar_one()
        for vid in village_ids:
            self.db.execute(text(
                "INSERT INTO air_violation_locations (air_violation_id, village_id) VALUES (:a, :v)"
            ), {"a": air_id, "v": vid})
        if commit:
            self.db.commit()
        return air_id
