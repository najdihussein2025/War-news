from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.news.dtos.incident_dto import IncidentListParams
from app.news.repositories.incident_repository import IncidentRepository


def _sql(expression) -> str:
    return str(expression.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_visible_needs_verification_uses_stored_status_or_visible_open_flag() -> None:
    sql = _sql(IncidentRepository._needs_verification_column())
    assert "verification_status = 'needs_verification'" in sql
    assert "duplicate_flag" not in sql
    assert "EXISTS" in sql
    assert "incident_verification_flags.status = 'open'" in sql
    assert "visible_after IS NULL" in sql and "visible_after <= now()" in sql


def test_verification_type_filters_map_to_reason_codes() -> None:
    missing = " ".join(_sql(item) for item in IncidentRepository._list_filters(
        IncidentListParams(verification_type="casualty_missing_number")
    ))
    aggregate = " ".join(_sql(item) for item in IncidentRepository._list_filters(
        IncidentListParams(verification_type="casualty_aggregate_toll")
    ))
    duplicate = " ".join(_sql(item) for item in IncidentRepository._list_filters(
        IncidentListParams(verification_type="duplicate")
    ))
    assert "count_missing" in missing
    assert "aggregate_no_breakdown" in aggregate
    assert "duplicate_flag IS true" in duplicate


def test_has_casualties_includes_positive_missing_and_shared_toll_rows() -> None:
    sql = " ".join(_sql(item) for item in IncidentRepository._list_filters(
        IncidentListParams(has_casualties=True)
    ))
    assert "total_deaths" in sql and "total_injuries" in sql
    assert "count_missing" in sql
    assert "aggregate_no_breakdown" in sql


def test_duplicate_only_filter_is_separate_from_needs_verification() -> None:
    duplicate_sql = " ".join(_sql(item) for item in IncidentRepository._list_filters(
        IncidentListParams(duplicate_only=True)
    ))
    needs_sql = " ".join(_sql(item) for item in IncidentRepository._list_filters(
        IncidentListParams(verification_status="needs_verification")
    ))
    assert "duplicate_flag IS true" in duplicate_sql
    assert "verification_status = 'needs_verification'" in needs_sql
    assert "duplicate_flag" not in needs_sql


def test_verified_excludes_open_visible_flags() -> None:
    sql = " ".join(_sql(item) for item in IncidentRepository._list_filters(
        IncidentListParams(verification_status="verified")
    ))
    assert "NOT" in sql and "EXISTS" in sql


def test_payload_has_unique_incident_and_multiple_open_flags() -> None:
    incident_id = uuid4()
    flags = [
        SimpleNamespace(id=uuid4(), reason_code="count_missing", severity="review", detail={"summary": "A", "evidence_sentence": "one"}),
        SimpleNamespace(id=uuid4(), reason_code="aggregate_no_breakdown", severity="review", detail={"summary": "B", "evidence_sentence": "two"}),
    ]
    payload = IncidentRepository._verification_payload(incident_id, False, None, {incident_id: flags})
    assert payload["verification_status"] == "needs_verification"
    assert payload["verification_types"] == ["casualty_missing_number", "casualty_aggregate_toll"]
    assert len(payload["open_flags"]) == 2


def test_outside_range_count_only_for_needs_verification_views() -> None:
    assert IncidentRepository._outside_range_needs_verification_filters(IncidentListParams()) is None
    assert IncidentRepository._outside_range_needs_verification_filters(
        IncidentListParams(verification_status="needs_verification", event_date_from=None)
    ) is None


def test_outside_range_count_drops_the_date_range_and_keeps_other_filters() -> None:
    from datetime import date

    params = IncidentListParams(
        verification_status="needs_verification",
        village="Nabatieh",
        has_casualties=True,
        event_date_from=date(2026, 9, 1),
        event_date_to=date(2026, 9, 20),
    )
    sql = " ".join(_sql(item) for item in IncidentRepository._outside_range_needs_verification_filters(params))
    assert "incidents.event_date IS NULL OR incidents.event_date < '2026-09-01' OR incidents.event_date > '2026-09-20'" in sql
    assert "incidents.event_date >= " not in sql and "incidents.event_date <= " not in sql
    assert "%Nabatieh%" in sql
    assert "total_deaths" in sql
    assert "incident_verification_flags.status = 'open'" in sql


def test_outside_range_count_follows_check_type() -> None:
    params = IncidentListParams(verification_type="casualty_aggregate_toll")
    sql = " ".join(_sql(item) for item in IncidentRepository._outside_range_needs_verification_filters(params))
    assert "aggregate_no_breakdown" in sql
    assert "incidents.event_date IS NULL OR incidents.event_date < '2026" in sql


def test_duplicate_payload_does_not_promote_verification_status() -> None:
    incident_id = uuid4()
    payload = IncidentRepository._verification_payload(incident_id, True, None, {})
    assert payload["verification_types"] == ["duplicate"]
    assert "verification_status" not in payload
    assert "verification_reason" not in payload
    stored = IncidentRepository._verification_payload(incident_id, True, "Same strike as #12", {})
    assert "verification_reason" not in stored
