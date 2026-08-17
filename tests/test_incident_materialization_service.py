from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401
from app.news.models import Incident, IncidentDetail
from app.news.services.incident_materialization_service import (
    EXACT_HASH_CONSTRAINT,
    IncidentMaterializationService,
)


class _SessionStub:
    def __init__(
        self,
        *,
        commit_error: Exception | None = None,
        scalar_result=None,
    ) -> None:
        self.commit_error = commit_error
        self.scalar_result = scalar_result
        self.added: list[object] = []
        self.staged: list[object] = []
        self.committed: list[object] = []
        self.flush_calls = 0
        self.commit_calls = 0
        self.rollback_calls = 0
        self.scalar_calls = 0

    def add(self, value: object) -> None:
        self.added.append(value)
        self.staged.append(value)

    def flush(self) -> None:
        self.flush_calls += 1
        incident = next(
            (value for value in self.staged if isinstance(value, Incident)),
            None,
        )
        if incident is not None and incident.id is None:
            incident.id = uuid4()

    def commit(self) -> None:
        self.commit_calls += 1
        if self.commit_error is not None:
            raise self.commit_error
        self.committed.extend(self.staged)
        self.staged.clear()

    def rollback(self) -> None:
        self.rollback_calls += 1
        self.staged.clear()

    def scalar(self, _statement):
        self.scalar_calls += 1
        return self.scalar_result


def _match_result(
    *,
    village_status: str = "matched",
    condition_status: str = "matched",
    village_id: int | None = 976,
    condition_id: int | None = 5,
) -> dict:
    return {
        "raw_village_text": "المنصوري",
        "matched_village_id": village_id,
        "raw_condition_text": "قصف مدفعي",
        "village_confidence": 1.0,
        "condition_confidence": 0.8,
        "matched_condition_id": condition_id,
        "village_match_status": village_status,
        "condition_match_status": condition_status,
        "village_review_required": False,
        "condition_review_required": False,
    }


def _extraction_result() -> dict:
    return {
        "is_relevant": True,
        "village": "المنصوري",
        "action_description": "قصف مدفعي",
        "categories": {},
        "casualties": {
            "total_deaths": 8,
            "total_injuries": 13,
            "deaths": 3,
            "injuries": 7,
            "male_deaths": 2,
            "male_injuries": 4,
            "female_deaths": 1,
            "female_injuries": 2,
            "children_deaths": 0,
            "children_injuries": 1,
        },
        "model": "test-model",
        "extracted_at": "2026-08-17T10:00:00Z",
    }


def _representative(*, match_result: dict | None = None):
    return SimpleNamespace(
        id=42,
        source_id=9,
        raw_text="  خبر   عاجل ",
        message_datetime=datetime(2026, 8, 17, 12, 30, tzinfo=timezone.utc),
        content_embedding=[0.1, 0.2, 0.3],
        extraction_result=_extraction_result(),
        match_result=match_result if match_result is not None else _match_result(),
    )


def test_eligible_representative_inserts_incident_and_detail() -> None:
    db = _SessionStub()
    service = IncidentMaterializationService(db)  # type: ignore[arg-type]

    result = service.materialize(_representative())

    assert isinstance(result, Incident)
    assert db.flush_calls == 1
    assert db.commit_calls == 1
    assert db.rollback_calls == 0
    assert len(db.committed) == 2

    incident = next(value for value in db.committed if isinstance(value, Incident))
    detail = next(
        value for value in db.committed if isinstance(value, IncidentDetail)
    )
    assert incident.raw_message_id == 42
    assert incident.village_id == 976
    assert incident.condition_id == 5
    assert incident.source_id == 9
    assert incident.event_date.isoformat() == "2026-08-17"
    assert incident.event_time.hour == 12
    assert incident.khabar == "  خبر   عاجل "
    assert incident.khabar_embedding == [0.1, 0.2, 0.3]
    assert incident.created_by is None
    assert detail.incident_id == incident.id
    assert service.stats.inserted == 1


def test_casualty_fields_map_from_top_level_extraction_result() -> None:
    db = _SessionStub()
    service = IncidentMaterializationService(db)  # type: ignore[arg-type]

    service.materialize(_representative())

    incident = next(value for value in db.committed if isinstance(value, Incident))
    detail = next(
        value for value in db.committed if isinstance(value, IncidentDetail)
    )
    assert (
        incident.total_deaths,
        incident.total_injuries,
        incident.deaths,
        incident.injuries,
    ) == (8, 13, 3, 7)
    assert (
        detail.male_d,
        detail.male_i,
        detail.female_d,
        detail.female_i,
        detail.children_d,
        detail.children_i,
    ) == (2, 4, 1, 2, 0, 1)
    assert incident.exact_hash == hashlib.sha256(
        "خبر عاجل|976|5|2026-08-17".encode("utf-8")
    ).hexdigest()


@pytest.mark.parametrize("condition_id", [35, 36, 38])
def test_air_violation_condition_is_skipped(condition_id: int, caplog) -> None:
    db = _SessionStub()
    service = IncidentMaterializationService(db)  # type: ignore[arg-type]

    with caplog.at_level("INFO"):
        result = service.materialize(
            _representative(match_result=_match_result(condition_id=condition_id))
        )

    assert result is None
    assert db.added == []
    assert db.commit_calls == 0
    assert service.stats.skipped_air_violation_routed == 1
    assert service.stats.skipped_ineligible == 0
    assert f"routed to air_violations, condition_id={condition_id}" in caplog.text


@pytest.mark.parametrize(
    "match_result",
    [
        _match_result(village_status="unmatched", village_id=None),
        _match_result(condition_status="unmatched", condition_id=None),
    ],
)
def test_unmatched_village_or_condition_is_skipped(match_result: dict) -> None:
    db = _SessionStub()
    service = IncidentMaterializationService(db)  # type: ignore[arg-type]

    result = service.materialize(_representative(match_result=match_result))

    assert result is None
    assert db.added == []
    assert db.commit_calls == 0
    assert db.rollback_calls == 0
    assert service.stats.skipped_ineligible == 1


def test_exact_hash_conflict_is_skipped_gracefully(caplog) -> None:
    original_error = RuntimeError("duplicate key")
    original_error.diag = SimpleNamespace(  # type: ignore[attr-defined]
        constraint_name=EXACT_HASH_CONSTRAINT
    )
    conflict = IntegrityError("INSERT", {}, original_error)
    existing_id = uuid4()
    db = _SessionStub(
        commit_error=conflict,
        scalar_result=SimpleNamespace(id=existing_id),
    )
    service = IncidentMaterializationService(db)  # type: ignore[arg-type]

    with caplog.at_level("INFO"):
        result = service.materialize(_representative())

    assert result is None
    assert db.rollback_calls == 1
    assert db.committed == []
    assert db.scalar_calls == 1
    assert service.stats.skipped_duplicate_hash == 1
    assert "incident already exists for this hash, skipping" in caplog.text
    assert str(existing_id) in caplog.text


def test_incident_and_detail_commit_atomically() -> None:
    db = _SessionStub(commit_error=RuntimeError("commit failed"))
    service = IncidentMaterializationService(db)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="commit failed"):
        service.materialize(_representative())

    assert len(db.added) == 2
    assert any(isinstance(value, Incident) for value in db.added)
    assert any(isinstance(value, IncidentDetail) for value in db.added)
    assert db.commit_calls == 1
    assert db.rollback_calls == 1
    assert db.committed == []
