"""Reproduction and regression tests for casualty status-transition merges."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401
from app.llm.dtos import ExtractionCasualties
from app.news.models import Incident, IncidentUpdate, UpdateAction
from app.news.repositories.incident_repository import IncidentRepository
from app.news.services.category_mapper import compute_rollups


class _MergeSessionStub:
    def __init__(self, *, raw_message: object | None = None) -> None:
        self.raw_message = raw_message or SimpleNamespace(
            source_name="CNRS Webhook",
            origin_account=None,
            source_platform=None,
            raw_text="بقي 3 جرحى وتوفي واحد من جرحى الغارة السابقة",
        )
        self.added: list[object] = []

    def get(self, model, pk):
        if model.__name__ == "RawMessage":
            return self.raw_message
        return None

    def scalar(self, _statement):
        return None

    def add(self, value: object) -> None:
        self.added.append(value)

    def flush(self) -> None:
        return None


def _followup_candidate_data(
    *,
    deaths: int | None,
    injuries: int | None,
    casualty_transitions: list[dict] | None = None,
) -> dict:
    casualties = ExtractionCasualties(deaths=deaths, injuries=injuries)
    total_deaths, total_injuries = compute_rollups({}, casualties)
    payload = {
        "deaths": casualties.deaths,
        "injuries": casualties.injuries,
        "total_deaths": total_deaths,
        "total_injuries": total_injuries,
        "khabar": "بقي 3 جرحى وتوفي واحد من جرحى الغارة السابقة",
    }
    if casualty_transitions is not None:
        payload["casualty_transitions"] = casualty_transitions
    return payload


def _injured_to_deceased(count: int) -> list[dict]:
    return [
        {
            "from_status": "injured",
            "to_status": "deceased",
            "count": count,
        }
    ]


def test_transition_followup_correct_extraction_merge_should_reflect_current_state() -> None:
    existing = Incident(
        id=uuid4(),
        deaths=0,
        injuries=4,
        total_deaths=0,
        total_injuries=4,
        details_pending=False,
    )
    repo = IncidentRepository(_MergeSessionStub())  # type: ignore[arg-type]

    repo.merge_existing(
        existing,
        _followup_candidate_data(
            deaths=1,
            injuries=3,
            casualty_transitions=_injured_to_deceased(1),
        ),
        raw_message_id=9001,
    )

    assert existing.deaths == 1
    assert existing.injuries == 3
    assert existing.total_deaths == 1
    assert existing.total_injuries == 3


def test_transition_followup_incremental_death_only_merge_applies_transition() -> None:
    existing = Incident(
        id=uuid4(),
        deaths=0,
        injuries=4,
        total_deaths=0,
        total_injuries=4,
        details_pending=False,
    )
    repo = IncidentRepository(_MergeSessionStub())  # type: ignore[arg-type]

    repo.merge_existing(
        existing,
        _followup_candidate_data(
            deaths=1,
            injuries=None,
            casualty_transitions=_injured_to_deceased(1),
        ),
        raw_message_id=9002,
    )

    assert existing.deaths == 1
    assert existing.injuries == 3


def test_transition_wins_over_conflicting_restated_injury_count() -> None:
    existing = Incident(
        id=uuid4(),
        deaths=0,
        injuries=4,
        total_deaths=0,
        total_injuries=4,
        details_pending=False,
    )
    repo = IncidentRepository(_MergeSessionStub())  # type: ignore[arg-type]

    repo.merge_existing(
        existing,
        _followup_candidate_data(
            deaths=1,
            injuries=2,
            casualty_transitions=_injured_to_deceased(1),
        ),
        raw_message_id=9003,
    )

    assert existing.injuries == 3
    assert existing.deaths == 1


def test_transition_clamps_at_zero_and_flags_review() -> None:
    existing = Incident(
        id=uuid4(),
        deaths=0,
        injuries=1,
        total_deaths=0,
        total_injuries=1,
        duplicate_flag=False,
        details_pending=False,
    )
    db = _MergeSessionStub()
    repo = IncidentRepository(db)  # type: ignore[arg-type]

    repo.merge_existing(
        existing,
        _followup_candidate_data(
            deaths=None,
            injuries=None,
            casualty_transitions=_injured_to_deceased(2),
        ),
        raw_message_id=9004,
    )

    assert existing.injuries == 0
    assert existing.deaths == 1
    assert existing.duplicate_flag is True
    assert existing.verification_status == "needs_verification"
    update = next(item for item in db.added if isinstance(item, IncidentUpdate))
    assert update.action == UpdateAction.pipeline_merge
    assert update.new_values["deaths_transitioned_from_injuries"]["requested_count"] == 2
    assert update.new_values["deaths_transitioned_from_injuries"]["count"] == 1


def test_backstop_flags_possible_missed_transition_for_review() -> None:
    existing = Incident(
        id=uuid4(),
        deaths=0,
        injuries=2,
        total_deaths=0,
        total_injuries=2,
        duplicate_flag=False,
        details_pending=False,
    )
    db = _MergeSessionStub(
        raw_message=SimpleNamespace(
            source_name="CNRS Webhook",
            origin_account=None,
            source_platform=None,
            raw_text="أعلنت وزارة الصحة وفاة أحد المصابين في قصف حولا متأثراً بجراحه.",
        )
    )
    repo = IncidentRepository(db)  # type: ignore[arg-type]

    repo.merge_existing(
        existing,
        _followup_candidate_data(
            deaths=1,
            injuries=None,
            casualty_transitions=[],
        ),
        raw_message_id=9005,
    )

    assert existing.duplicate_flag is True
    update = next(item for item in db.added if isinstance(item, IncidentUpdate))
    assert update.action == UpdateAction.pipeline_merge
    assert (
        update.new_values["possible_missed_casualty_transition"]["note"]
        == "possible casualty transition detected in text but not extracted - needs verification"
    )
    assert (
        "وفاة أحد المصابين متأثراً بجراحه"
        in update.new_values["possible_missed_casualty_transition"]["matched_keywords"]
    )
