"""The casualties filter / KPI rule: only a real death or injury count qualifies."""

import pytest
from sqlalchemy import create_engine, literal_column, select
from sqlalchemy.dialects import postgresql

from app.news.dtos.incident_dto import IncidentListParams
from app.news.models import Incident
from app.news.repositories.incident_repository import IncidentRepository
from app.news.repositories.reported_casualties import has_reported_casualties_expression

_DETAIL_COLUMNS = ("male_d", "male_i", "female_d", "female_i", "children_d", "children_i")


def _sql(expression) -> str:
    return str(expression.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


@pytest.fixture()
def evaluate():
    """Run the real expression on mirror tables holding only the columns it reads."""
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE incidents (id TEXT PRIMARY KEY, total_deaths INTEGER, total_injuries INTEGER)")
        conn.exec_driver_sql(
            f"CREATE TABLE incident_details (incident_id TEXT, {', '.join(f'{c} INTEGER' for c in _DETAIL_COLUMNS)})"
        )

    def run(total_deaths=None, total_injuries=None, **detail) -> bool:
        with engine.begin() as conn:
            conn.exec_driver_sql("DELETE FROM incidents")
            conn.exec_driver_sql("DELETE FROM incident_details")
            conn.exec_driver_sql(
                "INSERT INTO incidents VALUES ('i', ?, ?)", (total_deaths, total_injuries)
            )
            if detail:
                columns = ", ".join(detail)
                marks = ", ".join("?" for _ in detail)
                conn.exec_driver_sql(
                    f"INSERT INTO incident_details (incident_id, {columns}) VALUES ('i', {marks})",
                    tuple(detail.values()),
                )
            row = conn.execute(
                select(literal_column("incidents.id"), has_reported_casualties_expression()).select_from(
                    Incident.__table__
                )
            ).one()
            return bool(row[1])

    return run


def test_numbers_present_are_included(evaluate) -> None:
    assert evaluate(total_deaths=2) is True
    assert evaluate(total_injuries=5) is True
    assert evaluate(total_deaths=0, total_injuries=3) is True


def test_keyword_only_without_a_number_is_excluded(evaluate) -> None:
    # «وقوع إصابات»: counts stay null, only casualty_status = count_missing is set.
    assert evaluate() is False
    assert evaluate(total_deaths=None, total_injuries=None, male_d=None, children_i=None) is False


def test_all_counts_zero_or_null_are_excluded(evaluate) -> None:
    assert evaluate(total_deaths=0, total_injuries=0) is False
    assert evaluate(total_deaths=0, total_injuries=None, male_d=0, male_i=0, female_d=0, female_i=0, children_d=0, children_i=None) is False


@pytest.mark.parametrize("column", _DETAIL_COLUMNS)
def test_a_single_demographic_count_is_included(evaluate, column) -> None:
    assert evaluate(**{column: 1}) is True


def test_expression_reads_counts_only() -> None:
    sql = _sql(has_reported_casualties_expression())
    for forbidden in ("casualty_status", "count_missing", "aggregate_no_breakdown", "incident_verification_flags"):
        assert forbidden not in sql


def test_list_filter_uses_the_shared_expression_and_no_flag_conditions() -> None:
    sql = " ".join(_sql(item) for item in IncidentRepository._list_filters(IncidentListParams(has_casualties=True)))
    assert _sql(has_reported_casualties_expression()) in sql
    assert "count_missing" not in sql and "aggregate_no_breakdown" not in sql
    assert "incident_verification_flags" not in sql
