from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.news.models.incident_detail import IncidentDetail
from app.news.models.incident_update import UpdateAction
from app.news.services.incident_details.incident_casualty_recompute import (
    CasualtyValidationResult, ValidatedCasualtyClaim, demographic_total,
    derived_total, recompute_incident_casualties, resolved_casualty_values,
)


class _Rows:
    def __init__(self, values): self.values = values
    def all(self): return self.values


class _Db:
    def __init__(self, edits=(), detail=None):
        self.edits, self.detail, self.added = list(edits), detail, []
    def scalars(self, _statement): return _Rows(self.edits)
    def get(self, _model, _identifier): return self.detail
    def add(self, value): self.added.append(value)


def _incident(village_id=1, **values):
    defaults = dict(id=uuid4(), village_id=village_id, deaths=None, injuries=None,
                    total_deaths=None, total_injuries=None,
                    verification_status=None, verification_reason=None)
    defaults.update(values)
    return SimpleNamespace(**defaults)


def _validation(*claims, text_sources=1, stored_sources=1, disproved=0):
    villages = tuple(sorted({claim.village_name for claim in claims}))
    return CasualtyValidationResult(tuple(claims), (10,), text_sources,
                                    stored_sources, disproved, villages)


def _claim(village_id, village_name, **values):
    fields = {key: None for key in ("deaths", "injuries", "total_deaths",
                                     "total_injuries", "male_d", "male_i",
                                     "female_d", "female_i", "children_d", "children_i")}
    fields.update(values)
    return ValidatedCasualtyClaim(10, "raw_messages", village_id, village_name,
                                  fields, {key: "source quote" for key, value in values.items() if value is not None},
                                  owner_source=True)


def test_totals_are_derived_without_inventing_zero():
    assert derived_total(None, None) is None
    assert derived_total(None, 3, 2) == 3
    assert demographic_total(None, None) is None
    assert demographic_total(1, None, 2) == 3


def test_writer_ignores_and_clears_existing_incident_and_detail_values():
    incident = _incident(deaths=12, injuries=10, total_deaths=12, total_injuries=10)
    detail = IncidentDetail(incident_id=incident.id, male_d=2, female_i=3)
    db = _Db(detail=detail)
    validation = _validation(_claim(1, "Own village", injuries=5))
    assert recompute_incident_casualties(db, incident, reason_code="repair", validation=validation)
    assert (incident.deaths, incident.injuries, incident.total_deaths, incident.total_injuries) == (None, 5, None, 5)
    assert (detail.male_d, detail.female_i) == (None, None)
    assert len(db.added) == 1 and db.added[0].action == UpdateAction.pipeline_merge


def test_village_isolation_keeps_arabsalim_deaths_out_of_kfarrouman():
    result = _validation(_claim(118, "Aarab Salim", deaths=2), _claim(851, "Kfar Roummane", injuries=5))
    assert resolved_casualty_values(result, 118)[0]["deaths"] == 2
    kfar, _ = resolved_casualty_values(result, 851)
    assert (kfar["deaths"], kfar["injuries"], kfar["total_injuries"]) == (None, 5, 5)


def test_village_mismatch_clears_fields_and_sets_plain_reason():
    incident = _incident(village_id=543, deaths=1, injuries=9, total_deaths=1, total_injuries=9)
    db = _Db()
    result = _validation(_claim(1152, "Nabatieh Hay el-Maslakh", injuries=9))
    assert recompute_incident_casualties(db, incident, reason_code="repair", validation=result)
    assert (incident.deaths, incident.injuries) == (None, None)
    assert "Nabatieh Hay el-Maslakh" in incident.verification_reason
    assert "not this village" in incident.verification_reason


def test_admin_edit_wins():
    incident = _incident(deaths=2, total_deaths=2)
    db = _Db(edits=[{"deaths": 12}])
    assert not recompute_incident_casualties(db, incident, reason_code="merged", validation=_validation())
    assert incident.deaths == 2 and db.added == []


def test_creation_uses_create_audit_action():
    db, incident = _Db(), _incident()
    assert recompute_incident_casualties(db, incident, reason_code="created", creating=True,
                                        validation=_validation(_claim(1, "Own", deaths=1)))
    assert db.added[0].action == UpdateAction.create


def test_automatic_writer_rejects_unapproved_reason_codes():
    with pytest.raises(ValueError, match="reason_code"):
        recompute_incident_casualties(_Db(), _incident(), reason_code="edit", validation=_validation())
