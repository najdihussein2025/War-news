"""/api/analytics/tab/{tab}: filters applied, totals add up, empty periods return zeros.

Uses the scratch analytics database (see tests/analytics/support.py); skipped without it.
"""
from datetime import date, time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.analytics.services import refresh_service
from app.analytics.services import verification_reason_categories as reasons
from app.main import app
from tests.analytics.support import WARPLANE
from tests.analytics.test_api import D3, Q, client, data, fake_cache  # noqa: F401  (fixtures)

TABS = ["overview", "map", "incidents", "casualties", "air", "quality"]
EMPTY = "date_from=2026-01-01&date_to=2026-01-10"


@pytest.fixture()
def tab_data(world, db, data):
    """The API fixture world plus one air-violation-family incident and one 'count missing' toll."""
    saida = world.village("Saida")
    world.incident(village_id=saida, condition=WARPLANE, day=D3, commit=False)
    world.incident(village_id=saida, condition="Shooting", day=D3, status="needs_verification",
                   casualty_status="count_missing", commit=False)
    db.commit()
    refresh_service.full_rebuild(db)
    return data


def tab(client, name, query=Q):
    response = client.get(f"/api/analytics/tab/{name}?{query}")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("name", TABS)
def test_tab_requires_auth(name):
    app.dependency_overrides.clear()
    assert TestClient(app).get(f"/api/analytics/tab/{name}").status_code == 401


def test_unknown_tab_and_bad_grain_are_rejected(client, tab_data):
    assert client.get(f"/api/analytics/tab/planet?{Q}").status_code == 422
    assert client.get(f"/api/analytics/tab/overview?{Q}&grain=year").status_code == 422


@pytest.mark.parametrize("query", [Q, f"{Q}&include_pending=true", f"{Q}&area_code=LB63", f"{Q}&family=airstrikes"])
def test_kpi_incidents_equal_matrix_total(client, tab_data, query):
    """Fix 7a: air violations are not incidents, so the KPI and the matrix agree."""
    kpi = tab(client, "overview", query)["kpis"]["incidents"]["current"]
    incidents = tab(client, "incidents", query)
    for matrix in (incidents["matrix_caza"], incidents["matrix_mohafaza"]):
        assert matrix["grand_total"] + matrix["unplaced"] == kpi


def test_air_family_is_not_an_incident(client, tab_data):
    overview = tab(client, "overview")
    assert overview["kpis"]["incidents"]["current"] == 5  # the warplane-family incident is left out
    assert sum(v["value"] for v in overview["map"]["values"]) == 5
    assert "air_violations" not in {r["key"] for r in overview["action_share"]["rows"]}
    assert overview["kpis"]["pending_review"] == 2  # the review queue still sees everything pending


def test_filters_are_applied(client, tab_data):
    saida = tab(client, "overview", f"{Q}&area_code=LB61")
    assert saida["kpis"]["incidents"]["current"] == 1
    assert sum(v["value"] for v in saida["map"]["values"]) == 5  # the map ignores the area: all of Lebanon
    bombs = tab(client, "incidents", f"{Q}&family=airstrikes")
    assert bombs["matrix_caza"]["grand_total"] == 3
    assert [c["code"] for c in bombs["matrix_caza"]["columns"]] == ["airstrikes"]
    deaths = tab(client, "map", f"{Q}&metric=deaths")
    caza = next(v for v in deaths["rankings"]["views"] if v["id"] == "caza")
    assert caza["rows"][0]["code"] == "LB63" and caza["rows"][0]["value"] == 6
    pending = tab(client, "casualties", f"{Q}&include_pending=true")
    assert pending["kpis"]["deaths"]["current"] == 13  # + 7 from the pending Zahle incident


def test_totals_add_up(client, tab_data):
    overview = tab(client, "overview")
    kpis = overview["kpis"]
    n = kpis["incidents"]["current"]
    assert overview["action_share"]["total"] == n
    assert sum(p["value"] for p in overview["timeline"]["total"]) == n
    assert sum(p["deaths"] for p in overview["timeline"]["casualties"]) == kpis["deaths"]["current"]
    assert sum(r["current"] for r in overview["period_comparison"]["rows"]) == n

    incidents = tab(client, "incidents")
    assert sum(r["value"] for r in incidents["weekday"]["rows"]) == n
    assert sum(s["total"] for s in incidents["weekly_caza"]["series"]) == n
    assert sum(r["incidents"] for r in incidents["war_months"]["rows"]) == n
    assert incidents["channels"]["total"] == n

    mapped = tab(client, "map")
    assert mapped["pareto"]["total"] == n and mapped["pareto"]["rows"][-1]["cumulative_pct"] == 100.0
    villages = next(v for v in mapped["rankings"]["views"] if v["id"] == "villages")
    assert villages["total"] == n and round(sum(r["share_pct"] for r in villages["rows"])) == 100

    casualties = tab(client, "casualties")
    assert sum(p["deaths"] for p in casualties["series"]["points"]) == kpis["deaths"]["current"]
    assert sum(p["injuries"] for p in casualties["series"]["points"]) == kpis["injuries"]["current"]
    assert sum(r["deaths"] for r in casualties["by_family"]) == kpis["deaths"]["current"]

    air = tab(client, "air")
    assert sum(t["current"] for t in air["by_type"]) == air["total"]["current"] == kpis["air_breaches"]["current"]
    assert sum(t["total"] for t in air["hour_reported"]["types"]) == 4  # four reports, all with a time
    warplanes = next(t for t in air["hour_reported"]["types"] if t["condition_id"] == WARPLANE)
    assert warplanes["hours"][10] == 1


def test_casualty_counters(client, tab_data):
    """Fix 7b: "X of N incidents report casualties; Y report casualties without a count"."""
    completeness = tab(client, "casualties")["completeness"]
    assert completeness["incidents"] == 5 and completeness["with_casualties"] == 4 and completeness["count_missing"] == 0
    withp = tab(client, "casualties", f"{Q}&include_pending=true")["completeness"]
    assert withp["with_casualties"] == 5 and withp["count_missing"] == 1


def test_escalation_uses_the_last_day_with_data(client, tab_data, db):
    """Fix 7c: never compare a day that has no data yet; name an incomplete day."""
    esc = tab(client, "overview", "date_from=2026-10-01&date_to=2026-10-10")["kpis"]["escalation"]
    assert esc["requested_date"] == "2026-10-10"
    assert esc["latest"]["date"] == "2026-10-03" and esc["latest"]["value"] == 1
    assert esc["latest"]["average_30d"] == round(4 / 30, 2) and not esc["latest"]["incomplete"]
    db.execute(text("INSERT INTO analytics_dirty_dates (kind, event_date) VALUES ('incident', :d)"), {"d": D3})
    db.commit()
    refresh_service.bump_cache_version()
    esc = tab(client, "overview", "date_from=2026-10-01&date_to=2026-10-10")["kpis"]["escalation"]
    assert esc["latest"]["incomplete"] and esc["last_complete"]["date"] == "2026-10-02"
    assert esc["last_complete"]["value"] == 2


@pytest.mark.parametrize("name", TABS)
def test_empty_period_returns_zeros(client, tab_data, name):
    body = tab(client, name, EMPTY)
    if name in ("overview", "casualties"):
        assert body["kpis"]["incidents"]["current"] == 0 and body["kpis"]["deaths"]["current"] == 0
    if name == "overview":
        assert body["map"]["values"] == [] and body["action_share"]["rows"] == []
        assert all(p["value"] == 0 for p in body["timeline"]["total"])
    if name == "map":
        assert body["pareto"]["rows"] == [] and body["newly_targeted"]["rows"] == []
        assert all(v["rows"] == [] for v in body["rankings"]["views"])
    if name == "incidents":
        assert body["matrix_caza"]["grand_total"] == 0 and body["war_months"]["rows"] == []
        assert all(r["value"] == 0 for r in body["weekday"]["rows"]) and body["channels"]["total"] == 0
    if name == "casualties":
        assert body["incidents"]["total"] == 0 and body["by_caza"] == []
    if name == "air":
        assert body["total"]["current"] == 0 and all(t["total"] == 0 for t in body["hour_reported"]["types"])
    if name == "quality":
        assert body["pending_review"] == 0 and body["review_reasons"] == []


def test_newly_targeted_villages(client, tab_data):
    second_day = tab(client, "map", "date_from=2026-10-02&date_to=2026-10-03")["newly_targeted"]["rows"]
    # Sour village 0 was first hit on Oct 1, so only villages first hit on Oct 2-3 are new.
    assert second_day and all(r["first_date"] >= "2026-10-02" for r in second_day)


def test_reason_category_sql_matches_python(db):
    samples = [None, "", "Action could not be classified from the report", "100% similar to an existing incident",
               "Unsupported casualty_scope=per_village_exact", "Low-confidence village match requires review.",
               "not related", "possible duplicate of an existing incident (similarity segment)"]
    for sample in samples:
        got = db.execute(text(f"SELECT {reasons.case_sql('r')} FROM (SELECT CAST(:r AS text) AS r) t"),
                         {"r": sample}).scalar_one()
        assert got == reasons.categorize(sample), sample
