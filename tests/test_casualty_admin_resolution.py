import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.verification_flags_router import (
    ResolutionEntry,
    ResolveRequest,
    _apply_casualty_values,
    _distribution_errors,
    resolve,
)
from app.news.models import (
    BulletinCasualtyGroup,
    BulletinCasualtyGroupMember,
    Incident,
    IncidentDetail,
    IncidentUpdate,
    UpdateAction,
)
from app.news.models.bulletin_casualty_group import BulletinBreakdownStatus, CasualtyScope
from app.news.services.incident_details.admin_casualty_validation import (
    AdminCasualtyValidationError,
    validate_admin_casualties,
)


USER = SimpleNamespace(id=uuid4())
OWNER_VALUES = {
    "total_deaths": 2, "male_d": 1, "female_d": 1, "children_d": 0,
    "total_injuries": 3, "male_i": 1, "female_i": 1, "children_i": 1,
}
MEMBER_VALUES = {
    "total_deaths": 1, "male_d": 0, "female_d": 0, "children_d": 1,
    "total_injuries": 1, "male_i": 1, "female_i": 0, "children_i": 0,
}


def values(**overrides):
    result = {
        "total_deaths": 3, "male_d": 1, "female_d": 1, "children_d": 1,
        "total_injuries": 4, "male_i": 1, "female_i": 1, "children_i": 2,
    }
    result.update(overrides)
    return result


def test_resolution_entry_accepts_all_eight_values():
    entry = ResolutionEntry(incident_id=uuid4(), **values())
    assert entry.model_dump(include=set(values())) == values()


@pytest.mark.parametrize("field,bad", [("male_d", -1), ("total_injuries", 1.5)])
def test_admin_values_reject_negative_and_fractional_counts(field, bad):
    with pytest.raises(AdminCasualtyValidationError, match="non-negative integer"):
        validate_admin_casualties(values(**{field: bad}))


def test_admin_values_reject_breakdown_above_total():
    with pytest.raises(AdminCasualtyValidationError, match="breakdown"):
        validate_admin_casualties(values(total_deaths=2))


def test_linked_distribution_happy_path_and_mismatch():
    first, second = uuid4(), uuid4()
    allocation = {first: values(total_deaths=1, male_d=1, female_d=0, children_d=0), second: values(total_deaths=2, male_d=0, female_d=1, children_d=1)}
    assigned, errors = _distribution_errors(allocation, 3, 8, override=False)
    assert assigned == {"total_deaths": 3, "total_injuries": 8}
    assert errors == []
    _, errors = _distribution_errors(allocation, 4, 8, override=False)
    assert errors[0]["code"] == "sum_mismatch"


def test_linked_distribution_override_accepts_mismatch():
    allocation = {uuid4(): values(total_deaths=2)}
    _, errors = _distribution_errors(allocation, 9, 4, override=True)
    assert errors == []


def test_count_missing_values_clear_status_and_preserve_status_only_audit_diff():
    incident = SimpleNamespace(
        total_deaths=None, total_injuries=None, deaths=None, injuries=None,
        casualty_status="count_missing", casualty_deaths_status="count_missing",
        casualty_injuries_status="none_mentioned", casualty_status_remaining_total={"deaths": 1},
        verification_status="needs_verification", verification_reason="missing count",
    )
    detail = SimpleNamespace(**{field: None for field in ("male_d", "female_d", "children_d", "male_i", "female_i", "children_i")})
    old, new = _apply_casualty_values(incident, detail, values(total_deaths=1, male_d=1, female_d=0, children_d=0))
    assert old["casualty_status"] == "count_missing"
    assert new["casualty_status"] == "exact"
    assert new["verification_status"] == "verified"
    assert new["verification_reason"] is None


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Session:
    """Answers resolve()'s queries from in-memory rows, keyed by the selected model."""

    def __init__(self, rows):
        self.rows = rows
        self.added = []
        self.statements = []
        self.committed = False

    def _matching(self, stmt):
        self.statements.append(stmt)
        return list(self.rows.get(stmt.column_descriptions[0]["entity"], []))

    def scalar(self, stmt):
        matches = self._matching(stmt)
        return matches[0] if matches else None

    def scalars(self, stmt):
        return _Rows(self._matching(stmt))

    def add(self, value):
        self.added.append(value)

    def flush(self):
        pass

    def commit(self):
        self.committed = True


def _incident(casualty_status="aggregate_only"):
    return SimpleNamespace(
        id=uuid4(), deaths=None, injuries=None, total_deaths=None, total_injuries=None,
        casualty_deaths_status="aggregate_only", casualty_injuries_status="aggregate_only",
        casualty_status=casualty_status, casualty_status_remaining_total=None,
        verification_status="needs_verification", verification_reason="missing",
    )


def _open_flag(incident_id, reason_code="aggregate_no_breakdown"):
    return SimpleNamespace(
        id=uuid4(), incident_id=incident_id, status="open", flag_type="casualty_check",
        reason_code=reason_code, detail={},
    )


def _linked_group(total_deaths=3, total_injuries=4):
    owner, member = _incident(), _incident()
    group = BulletinCasualtyGroup(
        id=1, raw_message_id=10, village_ids=[1, 2], casualty_scope=CasualtyScope.bulletin_aggregate,
        total_deaths=total_deaths, total_injuries=total_injuries,
        breakdown_status=BulletinBreakdownStatus.pending, owner_incident_id=owner.id,
    )
    members = [
        BulletinCasualtyGroupMember(group_id=1, village_id=1, ordinal=0, incident_id=owner.id),
        BulletinCasualtyGroupMember(group_id=1, village_id=2, ordinal=1, incident_id=member.id),
    ]
    flags = [_open_flag(owner.id), _open_flag(member.id)]
    session = _Session({
        Incident: [owner, member], IncidentDetail: [], BulletinCasualtyGroup: [group],
        BulletinCasualtyGroupMember: members,
    })
    return owner, member, group, flags, session


def _resolve(monkeypatch, session, flags, entries, **payload):
    class Repo:
        def __init__(self, _db):
            pass

        def get_by_id(self, _flag_id):
            return flags[0]

        def list_open_for_incident(self, incident_id):
            return [flag for flag in flags if flag.incident_id == incident_id and flag.status == "open"]

        def resolve_flag(self, flag_id, _user_id, resolution):
            flag = next(flag for flag in flags if flag.id == flag_id)
            flag.status = "resolved"
            flag.resolution = resolution

    monkeypatch.setattr("app.api.verification_flags_router.IncidentVerificationFlagRepository", Repo)
    monkeypatch.setattr(
        "app.api.verification_flags_router.CasualtyFlagEvaluator",
        lambda *_args, **_kwargs: SimpleNamespace(evaluate_incident=lambda _id: None),
    )
    return resolve(flags[0].id, ResolveRequest(entries=entries, **payload), session, USER)


def _errors(response):
    return json.loads(response.body)["errors"]


def _updates(session):
    return [item for item in session.added if isinstance(item, IncidentUpdate)]


def test_linked_resolution_happy_path_resolves_every_row_together(monkeypatch):
    owner, member, group, flags, session = _linked_group()
    response = _resolve(monkeypatch, session, flags, [
        ResolutionEntry(incident_id=owner.id, **OWNER_VALUES),
        ResolutionEntry(incident_id=member.id, **MEMBER_VALUES),
    ])
    assert response["totals"]["deaths"] == {"assigned": 3, "bulletin_total": 3}
    assert (owner.total_deaths, member.total_deaths) == (2, 1)
    assert group.breakdown_status == BulletinBreakdownStatus.resolved
    assert all(flag.status == "resolved" for flag in flags)
    assert group.total_overridden is False
    assert session.committed


def test_every_linked_row_writes_one_audit_update(monkeypatch):
    owner, member, _group, flags, session = _linked_group()
    _resolve(monkeypatch, session, flags, [
        ResolutionEntry(incident_id=owner.id, **OWNER_VALUES),
        ResolutionEntry(incident_id=member.id, **MEMBER_VALUES),
    ])
    updates = _updates(session)
    assert sorted(str(update.incident_id) for update in updates) == sorted(str(i) for i in (owner.id, member.id))
    assert all(update.performed_by == USER.id for update in updates)
    owner_update = next(update for update in updates if update.incident_id == owner.id)
    assert owner_update.old_values["total_deaths"] is None
    assert owner_update.new_values["total_deaths"] == 2
    assert owner_update.new_values["casualty_resolution"] == "linked_group"


def test_sum_mismatch_is_rejected_without_writes(monkeypatch):
    owner, member, group, flags, session = _linked_group(total_deaths=4)
    response = _resolve(monkeypatch, session, flags, [
        ResolutionEntry(incident_id=owner.id, **OWNER_VALUES),
        ResolutionEntry(incident_id=member.id, **MEMBER_VALUES),
    ])
    assert response.status_code == 422
    errors = _errors(response)
    assert [(error["code"], error["field"]) for error in errors] == [("sum_mismatch", "total_deaths")]
    assert session.added == []
    assert not session.committed
    assert group.breakdown_status == BulletinBreakdownStatus.pending
    assert all(flag.status == "open" for flag in flags)


def test_partial_group_submission_is_rejected(monkeypatch):
    owner, _member, _group, flags, session = _linked_group()
    response = _resolve(monkeypatch, session, flags, [ResolutionEntry(incident_id=owner.id, **OWNER_VALUES)])
    assert response.status_code == 422
    assert "incomplete_group" in [error["code"] for error in _errors(response)]
    assert session.added == []


def test_invariant_violation_in_one_row_is_reported_with_its_incident(monkeypatch):
    owner, member, _group, flags, session = _linked_group()
    bad = {**OWNER_VALUES, "total_deaths": 1}
    response = _resolve(monkeypatch, session, flags, [
        ResolutionEntry(incident_id=owner.id, **bad),
        ResolutionEntry(incident_id=member.id, **MEMBER_VALUES),
    ])
    assert response.status_code == 422
    error = next(error for error in _errors(response) if error["code"] == "invariant")
    assert error["incident_id"] == str(owner.id)
    assert error["field"] == "total_deaths"
    assert "breakdown" in error["message"]
    assert session.added == []


def test_override_without_reason_is_rejected(monkeypatch):
    owner, member, group, flags, session = _linked_group(total_deaths=4)
    response = _resolve(monkeypatch, session, flags, [
        ResolutionEntry(incident_id=owner.id, **OWNER_VALUES),
        ResolutionEntry(incident_id=member.id, **MEMBER_VALUES),
    ], override=True, override_reason="   ")
    assert response.status_code == 422
    assert [(error["code"], error["field"]) for error in _errors(response)] == [("required", "override_reason")]
    assert group.breakdown_status == BulletinBreakdownStatus.pending


def test_override_with_reason_is_accepted_and_recorded(monkeypatch):
    owner, member, group, flags, session = _linked_group(total_deaths=4)
    response = _resolve(monkeypatch, session, flags, [
        ResolutionEntry(incident_id=owner.id, **OWNER_VALUES),
        ResolutionEntry(incident_id=member.id, **MEMBER_VALUES),
    ], override=True, override_reason="  Bulletin total counts a missing village  ")
    assert response["totals"]["deaths"] == {"assigned": 3, "bulletin_total": 4}
    assert group.breakdown_status == BulletinBreakdownStatus.resolved
    assert group.total_overridden is True
    assert group.total_override_reason == "Bulletin total counts a missing village"
    assert group.total_override_by_user_id == USER.id
    assert group.total_override_at is not None
    override_audit = [update for update in _updates(session) if update.new_values.get("total_overridden")]
    assert len(override_audit) == 1
    assert override_audit[0].incident_id == owner.id
    assert override_audit[0].new_values["override_reason"] == "Bulletin total counts a missing village"
    assert session.committed


def test_second_admin_gets_conflict_when_group_already_resolved(monkeypatch):
    owner, member, group, flags, session = _linked_group()
    group.breakdown_status = BulletinBreakdownStatus.resolved
    with pytest.raises(HTTPException) as raised:
        _resolve(monkeypatch, session, flags, [
            ResolutionEntry(incident_id=owner.id, **OWNER_VALUES),
            ResolutionEntry(incident_id=member.id, **MEMBER_VALUES),
        ])
    assert raised.value.status_code == 409
    assert "already resolved by another administrator" in raised.value.detail
    assert session.added == []
    assert not session.committed


def test_group_row_is_selected_for_update_before_values_are_written(monkeypatch):
    owner, member, _group, flags, session = _linked_group()
    _resolve(monkeypatch, session, flags, [
        ResolutionEntry(incident_id=owner.id, **OWNER_VALUES),
        ResolutionEntry(incident_id=member.id, **MEMBER_VALUES),
    ])
    group_query = next(stmt for stmt in session.statements if stmt.column_descriptions[0]["entity"] is BulletinCasualtyGroup)
    assert group_query._for_update_arg is not None


def test_count_missing_numbers_clear_verification_and_write_audit(monkeypatch):
    incident = _incident(casualty_status="count_missing")
    flag = _open_flag(incident.id, reason_code="count_missing")
    session = _Session({Incident: [incident], IncidentDetail: []})
    response = _resolve(monkeypatch, session, [flag], [ResolutionEntry(incident_id=incident.id, **OWNER_VALUES)])
    assert response["results"] == [{"incident_id": incident.id, "resolved": True, "still_open": False, "reason": "all_values_saved"}]
    assert incident.casualty_status == "exact"
    assert incident.verification_status == "verified"
    assert incident.verification_reason is None
    assert flag.status == "resolved"
    assert [update.action for update in _updates(session)] == [UpdateAction.edit]


def test_status_only_resolution_still_writes_audit_row(monkeypatch):
    incident = _incident(casualty_status="count_missing")
    flag = _open_flag(incident.id, reason_code="count_missing")
    session = _Session({Incident: [incident], IncidentDetail: []})
    response = _resolve(monkeypatch, session, [flag], [ResolutionEntry(incident_id=incident.id)])
    assert response["results"][0]["resolved"] is True
    assert incident.casualty_status == "none_mentioned"
    assert len(_updates(session)) == 1
    assert _updates(session)[0].new_values["casualty_resolution"] == "count_missing"
