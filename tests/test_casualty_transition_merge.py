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
from app.news.services.incident_details.category_mapper import compute_rollups


class _MergeSessionStub:
    def __init__(
        self,
        *,
        raw_message: object | None = None,
        transition_update_id: int | None = None,
    ) -> None:
        self.raw_message = raw_message or SimpleNamespace(
            source_name="CNRS Webhook",
            origin_account=None,
            source_platform=None,
            raw_text="بقي 3 جرحى وتوفي واحد من جرحى الغارة السابقة",
        )
        self.transition_update_id = transition_update_id
        self.scalar_calls = 0
        self.added: list[object] = []

    def get(self, model, pk):
        if model.__name__ == "RawMessage":
            return self.raw_message
        return None

    def scalar(self, _statement):
        self.scalar_calls += 1
        return self.transition_update_id if self.scalar_calls > 1 else None

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


def test_ungrounded_transition_is_ignored_for_separate_casualty_groups() -> None:
    existing = Incident(
        id=uuid4(),
        deaths=9,
        injuries=5,
        total_deaths=9,
        total_injuries=5,
        details_pending=False,
    )
    db = _MergeSessionStub(
        raw_message=SimpleNamespace(
            source_name="Telegram",
            origin_account=None,
            source_platform=None,
            raw_text=(
                "أدت الغارة على منزل إلى 8 شهداء و11 جريحا، "
                "والغارة على سيارة إلى شهيد وجريحين"
            ),
        )
    )

    IncidentRepository(db).merge_existing(  # type: ignore[arg-type]
        existing,
        _followup_candidate_data(
            deaths=9,
            injuries=13,
            casualty_transitions=_injured_to_deceased(1),
        ),
        raw_message_id=5050,
    )

    assert existing.deaths == 9
    assert existing.injuries == 13


def test_same_raw_message_transition_is_applied_only_once() -> None:
    existing = Incident(
        id=uuid4(),
        deaths=10,
        injuries=4,
        total_deaths=10,
        total_injuries=4,
        details_pending=False,
    )
    db = _MergeSessionStub(transition_update_id=1178)

    IncidentRepository(db).merge_existing(  # type: ignore[arg-type]
        existing,
        _followup_candidate_data(
            deaths=None,
            injuries=None,
            casualty_transitions=_injured_to_deceased(1),
        ),
        raw_message_id=5050,
    )

    assert existing.deaths == 10
    assert existing.injuries == 4


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
    assert existing.verification_reason is not None
    assert existing.verification_reason.startswith(
        "Possible duplicate — casualty count conflict detected during merge."
    )
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
    assert existing.verification_status == "needs_verification"
    assert existing.verification_reason is not None
    assert existing.verification_reason.startswith(
        "Possible duplicate — casualty count conflict detected during merge."
    )
    assert "Matched terms:" in existing.verification_reason
    update = next(item for item in db.added if isinstance(item, IncidentUpdate))
    matched_keyword = update.new_values["possible_missed_casualty_transition"][
        "matched_keywords"
    ][0]
    assert (
        matched_keyword
        in existing.verification_reason
    )
    assert update.action == UpdateAction.pipeline_merge
    assert (
        update.new_values["possible_missed_casualty_transition"]["note"]
        == "possible casualty transition detected in text but not extracted - needs verification"
    )
    assert (
        "وفاة أحد المصابين متأثراً بجراحه"
        in update.new_values["possible_missed_casualty_transition"]["matched_keywords"]
    )


def test_clean_resolved_merge_clears_verification_reason() -> None:
    existing = Incident(
        id=uuid4(),
        deaths=0,
        injuries=2,
        total_deaths=0,
        total_injuries=2,
        duplicate_flag=True,
        details_pending=False,
        verification_status="needs_verification",
        verification_reason="stale reason",
    )
    db = _MergeSessionStub(
        raw_message=SimpleNamespace(
            source_name="CNRS Webhook",
            origin_account=None,
            source_platform=None,
            raw_text="Ø£ØµÙŠØ¨ Ø´Ø®ØµØ§Ù† ÙÙŠ Ø§Ù„Ø­Ø§Ø¯Ø«.",
        )
    )
    repo = IncidentRepository(db)  # type: ignore[arg-type]

    repo.merge_existing(
        existing,
        _followup_candidate_data(
            deaths=0,
            injuries=2,
            casualty_transitions=[],
        ),
        raw_message_id=9006,
    )

    assert existing.duplicate_flag is False
    assert existing.verification_reason is None
