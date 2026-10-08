"""Scratch-database helpers for summary-flow integration tests.

These tests need a real PostgreSQL (row locks, JSONB, enums). They run only when
SUMMARY_TEST_DATABASE_URL points at a database whose name ends with "scratch";
the fixture TRUNCATEs tables, so it refuses anything else.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401
from app.news.models import Condition, Incident, MessageStatus, RawMessage, Village
from app.news.models.summary_bulletin import (
    SummaryBulletin,
    SummaryItem,
    SummaryKind,
    SummaryModifier,
    SummaryResolution,
    SummaryStatus,
)
from app.sources.models import Source, SourceType

BEIRUT = ZoneInfo("Asia/Beirut")
TABLES = (
    "summary_review_tasks, summary_items, summary_bulletins, summary_header_mappings, "
    "duplicate_matches, incident_updates, incident_details, incidents, raw_messages, "
    "village_location_aliases, villages, conditions, sources, users"
)
CONDITIONS = (
    "Bombs", "Warning Raid", "Artillery Shelling", "Tank Fire", "Flare Bomb",
    "Mining & Detonation", "Grenades", "Sweeping Operations",
)


def scratch_engine():
    url = os.environ.get("SUMMARY_TEST_DATABASE_URL")
    if not url:
        pytest.skip("SUMMARY_TEST_DATABASE_URL (a *scratch database) is required")
    engine = create_engine(url)
    if not (engine.url.database or "").endswith("scratch"):
        pytest.skip("refusing to truncate a database whose name does not end with 'scratch'")
    return engine


@dataclass
class World:
    engine: object
    session: Session
    source_id: int
    condition: dict[str, int]
    village: dict[str, int]
    window_start: datetime
    window_end: datetime


def build_world() -> World:
    engine = scratch_engine()
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    session = Session(engine)
    source = Source(type=SourceType.telegram, name="قناة اختبار")
    session.add(source)
    conditions = {name: Condition(action_en=name, action_ar=f"ar-{name}") for name in CONDITIONS}
    villages = {
        key: Village(acs_code=code, ref_name_ar=key, ref_name_en=key, caza_en="Sour")
        for code, key in enumerate(("A", "B", "C", "D"), start=1)
    }
    session.add_all([*conditions.values(), *villages.values()])
    session.flush()
    world = World(
        engine, session, source.id,
        {k: v.id for k, v in conditions.items()},
        {k: v.id for k, v in villages.items()},
        datetime(2026, 10, 7, 0, 0, tzinfo=BEIRUT),
        datetime(2026, 10, 8, 0, 0, tzinfo=BEIRUT),
    )
    session.commit()
    return world


def add_incident(world: World, *, village: str, condition: str, at: datetime, **kwargs) -> Incident:
    incident = Incident(
        village_id=world.village[village], condition_id=world.condition[condition],
        event_date=at.date(), event_time=at.time(), khabar=kwargs.pop("khabar", "خبر مباشر"),
        source_id=world.source_id, **kwargs,
    )
    world.session.add(incident)
    world.session.flush()
    return incident


def add_summary(
    world: World, items: list[dict], *, channel: str = "قناة اختبار", status=SummaryStatus.parsed,
    window: tuple[datetime, datetime] | None = None, text_value: str = "ملخص",
) -> SummaryBulletin:
    raw = RawMessage(
        source_id=world.source_id, raw_text=text_value, raw_payload={}, status=MessageStatus.summary_handled,
        external_message_id=f"m{datetime.now().timestamp()}-{channel}", source_name=channel,
    )
    world.session.add(raw)
    world.session.flush()
    start, end = window or (world.window_start, world.window_end)
    summary = SummaryBulletin(
        raw_message_id=raw.id, source_id=world.source_id, channel=channel, kind=SummaryKind.full_day,
        window_start=start, window_end=end, window_basis="default", fingerprint=f"fp-{raw.id}",
        status=status, parser_version="test",
    )
    world.session.add(summary)
    world.session.flush()
    for position, spec in enumerate(items):
        spec = dict(spec)
        village = spec.pop("village", "A")
        secondary = spec.pop("secondary", None)
        condition = spec.pop("condition", "Bombs")
        world.session.add(SummaryItem(
            summary_id=summary.id, position=position, header_text=spec.pop("header", "الغارات"),
            condition_id=world.condition[condition], location_text=spec.pop("location", village),
            primary_village_id=world.village[village],
            secondary_village_id=world.village[secondary] if secondary else None,
            modifier=SummaryModifier.between if secondary else SummaryModifier.none,
            evidence_span=spec.pop("evidence", f"- {village}"), resolution=SummaryResolution.resolved,
            **spec,
        ))
    world.session.flush()
    return summary


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=BEIRUT).replace(tzinfo=None)
