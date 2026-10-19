from uuid import uuid4
from types import SimpleNamespace
import json

import pytest
from pydantic import ValidationError

from app.api.verification_flags_router import DismissRequest, ResolveRequest, ResolutionEntry, _entry_fields, _grouped_rows, _resolution_error, _summary_payload, _live_remaining_total, resolve
from app.news.repositories.incident_repository import IncidentRepository


class _Rows:
    def __init__(self, rows): self.rows = rows
    def all(self): return self.rows


class _DB:
    def __init__(self, incidents): self.incidents = {row.id: row for row in incidents}; self.added = []
    def scalars(self, _query): return _Rows(list(self.incidents.values()))
    def get(self, _model, key): return self.incidents.get(key)
    def add(self, value): self.added.append(value)
    def flush(self): pass
    def commit(self): pass


class _Repo:
    def __init__(self, selected, flags): self.selected = selected; self.flags = flags
    def get_by_id(self, _): return self.selected
    def list_open_for_incident(self, incident_id): return [flag for flag in self.flags if flag.incident_id == incident_id and flag.status == "open"]
    def resolve_flag(self, flag_id, _user_id, resolution):
        flag = next(flag for flag in self.flags if flag.id == flag_id); flag.status = "resolved"; flag.resolution = resolution; return flag
    def update_open_resolution(self, flag_id, resolution, detail):
        flag = next(flag for flag in self.flags if flag.id == flag_id); flag.resolution = resolution; flag.detail = detail; return flag


def _incident(incident_id):
    return SimpleNamespace(id=incident_id, deaths=None, injuries=None, total_deaths=5, total_injuries=4,
                           casualty_deaths_status="aggregate_only", casualty_injuries_status="aggregate_only",
                           casualty_status="aggregate_only", casualty_status_remaining_total={"deaths": 5, "injuries": 4})


def _flag(incident_id, siblings):
    return SimpleNamespace(id=uuid4(), incident_id=incident_id, status="open", flag_type="casualty_check",
                           reason_code="aggregate_no_breakdown", detail={"sibling_incident_ids": [str(value) for value in siblings],
                           "bulletin_totals": {"deaths": 5, "injuries": 4}, "remaining_total": {"deaths": 5, "injuries": 4}})


def _install_fakes(monkeypatch, incidents):
    flags = [_flag(row.id, [item.id for item in incidents]) for row in incidents]
    repo = _Repo(flags[0], flags)
    monkeypatch.setattr("app.api.verification_flags_router.IncidentVerificationFlagRepository", lambda _db: repo)
    monkeypatch.setattr("app.api.verification_flags_router.CasualtyFlagEvaluator", lambda *_args, **_kwargs: SimpleNamespace(evaluate_incident=lambda _id: None))
    return _DB(incidents), repo, flags


def test_resolution_preserves_negative_for_structured_endpoint_validation():
    entry = ResolutionEntry(incident_id=uuid4(), total_deaths=-1)
    assert entry.total_deaths == -1


def test_new_per_type_unknown_and_old_shorthand_are_accepted():
    incident_id = uuid4()
    entry = ResolutionEntry(incident_id=incident_id, unknown_deaths=True)
    assert _entry_fields(entry) == {"deaths"}
    assert ResolveRequest(confirmed_unknown=True).confirmed_unknown


def test_field_error_shape_is_stable():
    incident_id = uuid4()
    assert _resolution_error(incident_id, "injuries", "over_total", "Too many.") == {
        "incident_id": str(incident_id), "field": "injuries", "code": "over_total", "message": "Too many."
    }


def test_dismiss_reason_has_minimum_length():
    with pytest.raises(ValidationError):
        DismissRequest(reason="x")


def test_resolved_number_audit_marks_fields_as_protected_from_later_merges():
    class AuditDB:
        def scalars(self, _query): return _Rows([{"deaths": 2, "total_deaths": 2}])
    protected = IncidentRepository(AuditDB())._admin_edited_casualty_fields(uuid4())
    assert protected == {"deaths", "total_deaths"}


def test_aggregate_flags_group_by_source_and_partial_resolution_stays_open():
    source_id = 321
    incident_ids = [uuid4() for _ in range(5)]
    incidents = {value: SimpleNamespace(id=value, village_display_name=f"Place {index}", event_date=None, source=None) for index, value in enumerate(incident_ids)}
    flags = [SimpleNamespace(
        id=uuid4(), incident_id=value, source_message_id=source_id, flag_type="casualty_check",
        reason_code="aggregate_no_breakdown", status="resolved" if index < 2 else "open",
        severity="review", detail={}, created_at=index, resolved_at=None, resolved_by=None,
        resolution=None, auto_clear_reason=None,
    ) for index, value in enumerate(incident_ids)]
    rows = _grouped_rows(flags, incidents, "open")
    assert len(rows) == 1
    assert rows[0]["status"] == "open"
    assert rows[0]["group_size"] == 3
    assert len(rows[0]["incident_ids"]) == 3
    assert _summary_payload(flags) == {"total": 1, "by_reason": {"aggregate_no_breakdown": 1}}


def test_count_missing_flags_remain_individual_groups():
    flags = [SimpleNamespace(
        id=uuid4(), incident_id=uuid4(), source_message_id=99, flag_type="casualty_check",
        reason_code="count_missing", status="open", severity="review", detail={}, created_at=index,
        resolved_at=None, resolved_by=None, resolution=None, auto_clear_reason=None,
    ) for index in range(2)]
    assert len(_grouped_rows(flags, {}, "open")) == 2


def test_list_open_for_incident_skips_flag_resolved_earlier_in_session():
    # The session does not autoflush; the resolve endpoint re-evaluates before commit.
    from app.news.repositories.incident_verification_flag_repository import IncidentVerificationFlagRepository
    open_flag = SimpleNamespace(status="open"); resolved = SimpleNamespace(status="resolved")
    db = SimpleNamespace(scalars=lambda _query: _Rows([resolved, open_flag]))
    assert IncidentVerificationFlagRepository(db).list_open_for_incident(uuid4()) == [open_flag]


def test_sibling_flag_shows_remaining_after_partial_save_on_another_location():
    # Bulletin 32095: 3 deaths / 23 injured; Rmadiye was saved as 1 / 15 from a sibling's flag.
    siblings = [SimpleNamespace(deaths=1, injuries=15), SimpleNamespace(deaths=None, injuries=None), SimpleNamespace(deaths=None, injuries=None)]
    assert _live_remaining_total({"deaths": 3, "injuries": 23}, siblings) == {"deaths": 2, "injuries": 8}
    assert _live_remaining_total({"deaths": 3, "injuries": None}, siblings) == {"deaths": 2}
    assert _live_remaining_total({"deaths": 1}, [SimpleNamespace(deaths=4, injuries=0)]) == {"deaths": 0}
