from types import SimpleNamespace
from uuid import uuid4

from app.news.models import Incident, RawMessage
from app.news.services.casualty_flag_evaluator import CasualtyFlagEvaluator, evaluate_casualty_flags_safely


class Repo:
    def __init__(self, flags=(), reviewed=()): self.flags=list(flags); self.reviewed=set(reviewed); self.opened=[]; self.cleared=[]
    def list_open_for_incident(self, _): return self.flags
    def has_previously_reviewed(self, _, reason): return reason in self.reviewed
    def open_flag(self, **kwargs): self.opened.append(kwargs); return SimpleNamespace(**kwargs)
    def auto_clear(self, flag_id, reason): self.cleared.append((flag_id, reason))


class DB:
    def __init__(self, incident, message=None): self.incident=incident; self.message=message; self.flushed=False
    def get(self, model, key):
        if model is RawMessage: return self.message if self.message and self.message.id == key else None
        return self.incident if self.incident and self.incident.id == key else None
    def flush(self): self.flushed=True


class Evaluator(CasualtyFlagEvaluator):
    def __init__(self, incident, *, flags=(), reviewed=(), siblings=None, message=None, enabled=True):
        self.db=DB(incident, message); self.repository=Repo(flags, reviewed); self.enabled=enabled; self._test_siblings=siblings or [incident]
    def _siblings(self, _incident): return self._test_siblings
    def _has_admin_casualty_edit(self, _): return False
    def _canonical_id(self, _): return None


def incident(**values):
    defaults=dict(id=uuid4(), raw_message_id=10, is_deleted=False, verification_status="auto_processed",
                  casualty_status="none_mentioned", casualty_deaths_status="none_mentioned",
                  casualty_injuries_status="none_mentioned", casualty_status_remaining_total={},
                  casualty_status_evidence=None, deaths=None, injuries=None, total_deaths=None,
                  total_injuries=None, village_display_name="Tyre")
    defaults.update(values); return Incident(**defaults)


def test_setting_off_is_noop():
    evaluator=Evaluator(incident(casualty_injuries_status="count_missing"), enabled=False)
    assert evaluator.evaluate_incident(evaluator.db.incident.id) == {"opened":0,"updated":0,"auto_cleared":0,"skipped":1}


def test_count_missing_opens_with_affected_type_and_exact_other_count():
    row=incident(casualty_status="count_missing", casualty_injuries_status="count_missing",
                 casualty_deaths_status="exact", deaths=1, casualty_status_evidence="وقوع إصابات")
    evaluator=Evaluator(row); result=evaluator.evaluate_incident(row.id)
    assert result["opened"] == 1
    assert evaluator.repository.opened[0]["detail"]["affected_types"] == ["injuries"]
    assert evaluator.repository.opened[0]["detail"]["known_exact_counts"] == {"deaths": 1}


def test_exact_single_victim_opens_no_flag():
    row=incident(casualty_status="exact", casualty_deaths_status="exact", deaths=1)
    evaluator=Evaluator(row); assert evaluator.evaluate_incident(row.id)["opened"] == 0


def test_previously_dismissed_is_not_reopened():
    row=incident(casualty_status="count_missing", casualty_deaths_status="count_missing")
    evaluator=Evaluator(row, reviewed={"count_missing"}); result=evaluator.evaluate_incident(row.id)
    assert result["skipped"] == 1 and not evaluator.repository.opened


def test_previously_resolved_is_not_reopened():
    row=incident(casualty_status="count_missing", casualty_deaths_status="count_missing")
    evaluator=Evaluator(row, reviewed={"count_missing"}); result=evaluator.evaluate_incident(row.id)
    assert result["skipped"] == 1 and not evaluator.repository.opened


def test_number_arriving_auto_clears_open_count_missing():
    flag=SimpleNamespace(id=uuid4(), flag_type="casualty_check", reason_code="count_missing")
    row=incident(casualty_status="exact", casualty_deaths_status="exact", deaths=2)
    evaluator=Evaluator(row, flags=[flag]); result=evaluator.evaluate_incident(row.id)
    assert result["auto_cleared"] == 1


def test_partial_missing_update_keeps_same_flag_open():
    flag=SimpleNamespace(id=uuid4(), flag_type="casualty_check", reason_code="count_missing", visible_after=None)
    row=incident(casualty_status="count_missing", casualty_deaths_status="exact",
                 casualty_injuries_status="count_missing", deaths=2)
    evaluator=Evaluator(row, flags=[flag]); result=evaluator.evaluate_incident(row.id)
    assert result["updated"] == 1 and result["auto_cleared"] == 0


def test_aggregate_detail_names_owner_and_members_for_three_siblings():
    rows=[incident(raw_message_id=20, casualty_status="aggregate_only",
                   casualty_status_remaining_total={"deaths": 5}, total_deaths=5,
                   village_display_name=name) for name in ("Tyre", "Nabatieh", "Beirut")]
    details=[]
    for row in rows:
        evaluator=Evaluator(row, siblings=rows); evaluator.evaluate_incident(row.id)
        details.append(evaluator.repository.opened[0]["detail"])
    assert "تم وضع الحصيلة كاملة على هذا السجل" in details[0]["summary"]
    assert "مسجلة على سجل Tyre" in details[1]["summary"]
    assert "مسجلة على سجل Tyre" in details[2]["summary"]
    assert all(detail["bulletin_totals"] == details[0]["bulletin_totals"] for detail in details)
    assert len(details[0]["sibling_incident_ids"]) == 3


def test_message_snapshot_survives_raw_message_deletion():
    row=incident(casualty_status="count_missing", casualty_deaths_status="count_missing")
    message=RawMessage(id=10, raw_text="  casualty bulletin  ", source_name="News desk")
    first=Evaluator(row, message=message); first.evaluate_incident(row.id)
    snapshot=first.repository.opened[0]["detail"]
    flag=SimpleNamespace(id=uuid4(), flag_type="casualty_check", reason_code="count_missing",
                         visible_after=None, detail=snapshot)
    second=Evaluator(row, flags=[flag], message=None); second.evaluate_incident(row.id)
    assert second.repository.opened[0]["detail"]["message_text"] == "casualty bulletin"
    assert second.repository.opened[0]["detail"]["source_name"] == "News desk"


def test_safe_hook_swallows_evaluator_failure(monkeypatch):
    class Broken:
        def __init__(self, _db): pass
        def evaluate_incident(self, _id): raise RuntimeError("boom")
    monkeypatch.setattr("app.news.services.casualty_flag_evaluator.settings.casualty_flags_enabled", True)
    monkeypatch.setattr("app.news.services.casualty_flag_evaluator.CasualtyFlagEvaluator", Broken)
    evaluate_casualty_flags_safely(DB(None), uuid4())


def test_unchanged_open_flag_is_not_rewritten():
    row=incident(casualty_status="count_missing", casualty_deaths_status="count_missing", casualty_status_evidence="شهداء")
    first=Evaluator(row); first.evaluate_incident(row.id); opened=first.repository.opened[0]
    flag=SimpleNamespace(id=uuid4(), flag_type="casualty_check", reason_code="count_missing", severity="review",
                         detail=dict(opened["detail"]), source_message_id=10, visible_after=opened["visible_after"])
    evaluator=Evaluator(row, flags=[flag]); result=evaluator.evaluate_incident(row.id)
    assert result == {"opened":0,"updated":0,"auto_cleared":0,"skipped":0} and not evaluator.repository.opened


def test_aggregate_totals_come_from_status_when_row_totals_were_cleared():
    rows=[incident(raw_message_id=30, casualty_status="aggregate_only", casualty_deaths_status="aggregate_only",
                   casualty_injuries_status="aggregate_only", casualty_status_remaining_total={"deaths": 4, "injuries": 32},
                   village_display_name=name) for name in ("Nabatieh", "Kfour")]
    evaluator=Evaluator(rows[0], siblings=rows); evaluator.evaluate_incident(rows[0].id)
    assert evaluator.repository.opened[0]["detail"]["bulletin_totals"] == {"deaths": 4, "injuries": 32}


def test_admin_entries_on_siblings_do_not_become_the_bulletin_total():
    rows=[incident(raw_message_id=30, casualty_status="aggregate_only", casualty_deaths_status="aggregate_only",
                   casualty_injuries_status="aggregate_only", casualty_status_remaining_total={"deaths": 4, "injuries": 32},
                   village_display_name=name) for name in ("Nabatieh", "Kfour")]
    rows[1].deaths=rows[1].total_deaths=10; rows[1].casualty_deaths_status="exact"
    flag=SimpleNamespace(id=uuid4(), flag_type="casualty_check", reason_code="aggregate_no_breakdown", visible_after=None,
                         detail={"bulletin_totals": {"deaths": 4, "injuries": 32}})
    evaluator=Evaluator(rows[0], flags=[flag], siblings=rows); evaluator.evaluate_incident(rows[0].id)
    assert evaluator.repository.opened[0]["detail"]["bulletin_totals"] == {"deaths": 4, "injuries": 32}
