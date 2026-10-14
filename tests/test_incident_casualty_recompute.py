from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.news.models.incident_update import UpdateAction
from app.news.services.incident_details.incident_casualty_recompute import (
    demographic_total,
    derived_total,
    recompute_incident_casualties,
)


class _Rows:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class _Db:
    def __init__(self, edits=(), detail=None):
        self.edits = list(edits)
        self.detail = detail
        self.added = []

    def scalars(self, _statement):
        return _Rows(self.edits)

    def get(self, _model, _identifier):
        return self.detail

    def add(self, value):
        self.added.append(value)


def _incident(**values):
    defaults = {
        "id": uuid4(),
        "deaths": None,
        "injuries": None,
        "total_deaths": None,
        "total_injuries": None,
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


def test_totals_are_derived_without_inventing_zero():
    assert derived_total(None, None) is None
    assert derived_total(None, 3, 2) == 3
    assert demographic_total(None, None) is None
    assert demographic_total(1, None, 2) == 3


def test_recompute_derives_total_once_and_is_idempotent():
    db = _Db()
    incident = _incident(deaths=2, injuries=5)
    assert recompute_incident_casualties(db, incident, raw_message_ids=[10], reason_code="reconciled")
    assert incident.total_deaths == 2
    assert incident.total_injuries == 5
    assert len(db.added) == 1
    assert db.added[0].action == UpdateAction.pipeline_merge
    assert db.added[0].new_values["reason_code"] == "reconciled"
    assert not recompute_incident_casualties(db, incident, raw_message_ids=[10], reason_code="reconciled")
    assert len(db.added) == 1


def test_admin_edit_wins_and_no_cross_message_sum_is_possible():
    incident = _incident(deaths=2, injuries=1, total_deaths=2, total_injuries=1)
    db = _Db(edits=[{"deaths": 12}])
    assert not recompute_incident_casualties(db, incident, raw_message_ids=[5050, 5052], reason_code="merged")
    assert incident.total_deaths == 2
    assert incident.total_injuries == 1
    assert db.added == []


def test_creation_uses_create_audit_action_even_when_already_consistent():
    db = _Db()
    incident = _incident(deaths=1, total_deaths=1)
    assert recompute_incident_casualties(db, incident, reason_code="created", creating=True)
    assert db.added[0].action == UpdateAction.create
    assert db.added[0].new_values["reason_code"] == "created"


def test_automatic_writer_rejects_unapproved_reason_codes():
    with pytest.raises(ValueError, match="reason_code"):
        recompute_incident_casualties(_Db(), _incident(), reason_code="edit")
