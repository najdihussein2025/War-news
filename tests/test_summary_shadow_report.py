"""summary_shadow_report.py: read-only, writes a markdown report, touches no rows."""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.news.models import Incident
from app.news.models.summary_bulletin import SummaryBulletin
from app.news.services.summaries.reconcile_service import reconcile_summary
from scripts.summary_shadow_report import shadow_summaries
from tests.summary_db import add_summary, build_world


@pytest.fixture
def world():
    w = build_world()
    yield w
    w.session.rollback()
    w.session.close()


def test_shadow_summaries_only_returns_dry_run_rows_in_range(world):
    summary = add_summary(world, [{"village": "A"}])
    asyncio.run(reconcile_summary(world.session, summary.id, dry_run=True))
    world.session.commit()
    assert summary.shadow_result is not None

    in_range = shadow_summaries(world.session, date.today() - timedelta(days=1), date.today() + timedelta(days=1))
    assert [s.id for s in in_range] == [summary.id]

    out_of_range = shadow_summaries(world.session, date.today() + timedelta(days=5), date.today() + timedelta(days=6))
    assert out_of_range == []

    unparsed = add_summary(world, [{"village": "B"}], channel="غير معالج")
    world.session.commit()
    assert unparsed.id not in {s.id for s in shadow_summaries(world.session, date.today() - timedelta(days=1), date.today() + timedelta(days=1))}


def test_dry_run_reconcile_leaves_no_incidents_for_the_report_to_read(world):
    summary = add_summary(world, [{"village": "A"}])
    asyncio.run(reconcile_summary(world.session, summary.id, dry_run=True))
    world.session.commit()
    assert world.session.scalars(select(Incident)).all() == []
    assert world.session.scalars(select(SummaryBulletin)).all()  # the summary row itself exists
