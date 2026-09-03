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
from app.news.models import Incident, IncidentDetail, MessageStatus
from app.news.services.fast_path_dedup import FastPathDedupOutcome
from app.news.services.fast_path_eligibility import (
    ERROR_AIR_VIOLATION,
    ERROR_NO_VILLAGE,
    ERROR_UNMATCHED_CONDITION,
)
from app.news.services.incident_materialization_service import (
    EXACT_HASH_CONSTRAINT,
    IncidentMaterializationService,
    _initial_verification_status,
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

    def execute(self, _statement, _params=None):
        return None


def test_initial_verification_status_auto_processes_clean_exact_matches() -> None:
    assert _initial_verification_status(_match_result()) == "auto_processed"


@pytest.mark.parametrize(
    "signal",
    [
        "duplicate_flag",
        "relevance_needs_review",
        "insufficient_score",
        "possible_missed_casualty_transition",
    ],
)
def test_initial_verification_status_flags_each_uncertainty_signal(signal: str) -> None:
    assert (
        _initial_verification_status(_match_result(), **{signal: True})
        == "needs_verification"
    )


def test_initial_verification_status_flags_low_confidence_match() -> None:
    assert (
        _initial_verification_status(
            _match_result(village_status="matched_low_confidence")
        )
        == "needs_verification"
    )


# ---------------------------------------------------------------------------
# Helpers: build match_results in the new village_matches shape
# ---------------------------------------------------------------------------

def _match_result(
    *,
    village_status: str = "matched",
    condition_status: str = "matched",
    village_id: int | None = 976,
    condition_id: int | None = 5,
) -> dict:
    return {
        "village_matches": [
            {
                "raw_village_text": "المنصوري",
                "matched_village_id": village_id,
                "village_confidence": 1.0,
                "village_match_status": village_status,
                "village_review_required": village_status != "matched",
            }
        ],
        "any_village_low_confidence": village_status == "matched_low_confidence",
        "raw_condition_text": "قصف مدفعي",
        "condition_confidence": 0.8,
        "matched_condition_id": condition_id,
        "condition_match_status": condition_status,
        "condition_review_required": condition_status != "matched",
    }


def _two_village_match_result(
    *,
    village_id_a: int = 976,
    village_id_b: int = 977,
    condition_id: int = 5,
) -> dict:
    return {
        "village_matches": [
            {
                "raw_village_text": "المنصوري",
                "matched_village_id": village_id_a,
                "village_confidence": 1.0,
                "village_match_status": "matched",
                "village_review_required": False,
            },
            {
                "raw_village_text": "بنت جبيل",
                "matched_village_id": village_id_b,
                "village_confidence": 0.9,
                "village_match_status": "matched",
                "village_review_required": False,
            },
        ],
        "any_village_low_confidence": False,
        "raw_condition_text": "قصف مدفعي",
        "condition_confidence": 0.8,
        "matched_condition_id": condition_id,
        "condition_match_status": "matched",
        "condition_review_required": False,
    }


def _extraction_result() -> dict:
    return {
        "is_relevant": True,
        "village": ["المنصوري"],
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
        status=MessageStatus.parsed,
        error_message=None,
        fast_path_completed_at=None,
        tier2_completed_at=None,
        embedded_at=None,
        materialized_at=None,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_eligible_representative_inserts_incident_and_detail() -> None:
    db = _SessionStub()
    service = IncidentMaterializationService(db)  # type: ignore[arg-type]
    representative = _representative()

    result = service.materialize(representative)

    assert len(result) == 1
    assert isinstance(result[0], Incident)
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
    assert representative.status == MessageStatus.materialized


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
    ) == (3, 7, 3, 7)
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


def test_materialization_strips_emoji_from_khabar_and_hash() -> None:
    db = _SessionStub()
    service = IncidentMaterializationService(db)  # type: ignore[arg-type]
    representative = _representative()
    representative.raw_text = "🚨 \u062e\u0628\u0631   \u0639\u0627\u062c\u0644 🔴"

    service.materialize(representative)

    incident = next(value for value in db.committed if isinstance(value, Incident))
    assert incident.khabar == " \u062e\u0628\u0631   \u0639\u0627\u062c\u0644 "
    assert incident.exact_hash == hashlib.sha256(
        "\u062e\u0628\u0631 \u0639\u0627\u062c\u0644|976|5|2026-08-17".encode("utf-8")
    ).hexdigest()


def test_fast_path_strips_emoji_from_khabar_and_hash() -> None:
    db = _SessionStub()
    service = IncidentMaterializationService(db)  # type: ignore[arg-type]
    representative = _representative()
    representative.raw_text = "🚨 \u062e\u0628\u0631   \u0639\u0627\u062c\u0644 🔴"

    result = service.process_fast_path(
        representative,
        SimpleNamespace(
            decide_for_village=lambda **_kwargs: SimpleNamespace(
                outcome=FastPathDedupOutcome.materialize,
                representative_raw_message_id=None,
                canonical_incident_id=None,
            )
        ),
    )

    assert len(result) == 1
    incident = next(value for value in db.committed if isinstance(value, Incident))
    assert incident.khabar == " \u062e\u0628\u0631   \u0639\u0627\u062c\u0644 "
    assert incident.exact_hash == hashlib.sha256(
        "\u062e\u0628\u0631 \u0639\u0627\u062c\u0644|976|5|2026-08-17".encode("utf-8")
    ).hexdigest()
    assert representative.status == MessageStatus.materialized


@pytest.mark.parametrize("condition_id", [35, 36, 38])
def test_air_violation_condition_is_skipped(condition_id: int, caplog) -> None:
    db = _SessionStub()
    service = IncidentMaterializationService(db)  # type: ignore[arg-type]
    representative = _representative(match_result=_match_result(condition_id=condition_id))

    with caplog.at_level("INFO"):
        result = service.materialize(representative)

    assert result == []
    assert db.added == []
    assert db.commit_calls == 1
    assert representative.status == MessageStatus.routed_air_violation
    assert representative.error_message == ERROR_AIR_VIOLATION
    assert service.stats.skipped_air_violation_routed == 1
    assert service.stats.skipped_ineligible == 0
    assert "air_violations" in caplog.text


@pytest.mark.parametrize(
    "match_result, expected_reason",
    [
        (
            _match_result(village_status="unmatched", village_id=None),
            ERROR_NO_VILLAGE,
        ),
        (
            _match_result(condition_status="unmatched", condition_id=None),
            ERROR_UNMATCHED_CONDITION,
        ),
    ],
)
def test_unmatched_village_or_condition_is_skipped(
    match_result: dict,
    expected_reason: str,
) -> None:
    db = _SessionStub()
    service = IncidentMaterializationService(db)  # type: ignore[arg-type]
    representative = _representative(match_result=match_result)

    result = service.materialize(representative)

    assert result == []
    assert db.added == []
    assert db.commit_calls == 1
    assert db.rollback_calls == 0
    assert representative.status == MessageStatus.error
    assert representative.error_message == expected_reason
    assert service.stats.skipped_ineligible >= 1


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

    assert result == []
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


# ---------------------------------------------------------------------------
# Task-4: multi-village materialization tests
# ---------------------------------------------------------------------------

def test_two_village_match_produces_two_incidents() -> None:
    """A raw_message with two matched villages creates two separate Incident rows."""
    db = _SessionStub()
    service = IncidentMaterializationService(db)  # type: ignore[arg-type]
    representative = _representative(match_result=_two_village_match_result())

    result = service.materialize(representative)

    assert len(result) == 2
    assert db.commit_calls == 2  # one commit per village
    incidents = [value for value in db.committed if isinstance(value, Incident)]
    village_ids = {inc.village_id for inc in incidents}
    assert village_ids == {976, 977}
    # Both incidents share the same khabar
    assert all(inc.khabar == "  خبر   عاجل " for inc in incidents)
    assert service.stats.inserted == 2
    assert representative.status == MessageStatus.materialized


def test_old_flat_match_result_is_backward_compatible() -> None:
    """Pre-Task-4 flat match_result (without village_matches) still works."""
    old_match_result = {
        "raw_village_text": "المنصوري",
        "matched_village_id": 976,
        "village_confidence": 1.0,
        "village_match_status": "matched",
        "village_review_required": False,
        "raw_condition_text": "قصف مدفعي",
        "condition_confidence": 0.8,
        "matched_condition_id": 5,
        "condition_match_status": "matched",
        "condition_review_required": False,
    }
    db = _SessionStub()
    service = IncidentMaterializationService(db)  # type: ignore[arg-type]

    result = service.materialize(_representative(match_result=old_match_result))

    assert len(result) == 1
    assert result[0].village_id == 976
    assert service.stats.inserted == 1


# ---------------------------------------------------------------------------
# Task-5: dedup matching during materialization
# ---------------------------------------------------------------------------


class _DedupServiceStub:
    def __init__(self, *, existing: Incident | None, score: float) -> None:
        self.existing = existing
        self.score = score
        self.merge_calls: list[tuple[Incident, dict, int]] = []
        self.possible_duplicate_calls: list[
            tuple[Incident, Incident, float]
        ] = []

    def find_best_match(self, **_kwargs):
        return self.existing, self.score

    def merge_into_incident(
        self,
        existing: Incident,
        new_candidate_data: dict,
        raw_message_id: int,
    ) -> None:
        self.merge_calls.append((existing, new_candidate_data, raw_message_id))

    def record_possible_duplicate(
        self,
        incident: Incident,
        matched_incident: Incident,
        similarity_score: float,
    ) -> None:
        self.possible_duplicate_calls.append(
            (incident, matched_incident, similarity_score)
        )


def test_dedup_high_score_merges_and_skips_insert() -> None:
    existing = SimpleNamespace(id=uuid4())
    dedup = _DedupServiceStub(existing=existing, score=0.85)  # type: ignore[arg-type]
    db = _SessionStub()
    service = IncidentMaterializationService(db, dedup_service=dedup)  # type: ignore[arg-type]
    representative = _representative()

    result = service.materialize(representative)

    assert len(result) == 1
    assert result[0] is existing
    assert existing.duplicate_level == "high"
    assert existing.duplicate_similarity_score == 0.85
    assert len(dedup.merge_calls) == 1
    assert service.stats.merged_into_existing == 1
    assert service.stats.inserted == 0
    assert not any(isinstance(value, Incident) for value in db.committed)
    assert representative.status == MessageStatus.materialized


def test_dedup_mid_score_creates_incident_with_duplicate_flag() -> None:
    existing = SimpleNamespace(id=uuid4())
    dedup = _DedupServiceStub(existing=existing, score=0.65)  # type: ignore[arg-type]
    db = _SessionStub()
    service = IncidentMaterializationService(db, dedup_service=dedup)  # type: ignore[arg-type]

    result = service.materialize(_representative())

    assert len(result) == 1
    assert result[0].duplicate_flag is True
    assert result[0].verification_status == "needs_verification"
    assert result[0].duplicate_level == "medium"
    assert result[0].duplicate_similarity_score == 0.65
    assert service.stats.inserted == 1
    assert service.stats.merged_into_existing == 0
    assert len(dedup.possible_duplicate_calls) == 1

    new_incident, matched_incident, similarity_score = (
        dedup.possible_duplicate_calls[0]
    )

    assert new_incident is result[0]
    assert matched_incident is existing
    assert similarity_score == 0.65


def test_dedup_low_score_creates_incident_without_duplicate_flag() -> None:
    existing = SimpleNamespace(id=uuid4())
    dedup = _DedupServiceStub(existing=existing, score=0.30)  # type: ignore[arg-type]
    db = _SessionStub()
    service = IncidentMaterializationService(db, dedup_service=dedup)  # type: ignore[arg-type]

    result = service.materialize(_representative())

    assert len(result) == 1
    assert result[0].duplicate_flag is False
    assert result[0].verification_status == "auto_processed"
    assert result[0].duplicate_level == "low"
    assert result[0].duplicate_similarity_score == 0.30
    assert service.stats.inserted == 1
    assert dedup.possible_duplicate_calls == []


def test_dedup_skipped_when_no_embedding() -> None:
    dedup = _DedupServiceStub(existing=SimpleNamespace(id=uuid4()), score=0.99)  # type: ignore[arg-type]
    db = _SessionStub()
    service = IncidentMaterializationService(db, dedup_service=dedup)  # type: ignore[arg-type]
    representative = _representative()
    representative.content_embedding = None

    result = service.materialize(representative)

    assert len(result) == 1
    assert result[0].duplicate_flag is False
    assert dedup.merge_calls == []
    assert service.stats.inserted == 1


# ---------------------------------------------------------------------------
# Task-6: category fields passed through to incident_details
# ---------------------------------------------------------------------------


def test_category_fields_passed_to_incident_detail() -> None:
    extraction = _extraction_result()
    extraction["categories"] = {
        "lebanese_army": {
            "did": "D",
            "name": None,
            "casualties": {
                "male_deaths": 1,
                "male_injuries": 2,
                "female_deaths": None,
                "female_injuries": None,
                "children_deaths": None,
                "children_injuries": None,
                "deaths": None,
                "injuries": None,
                "total_deaths": None,
                "total_injuries": None,
            },
        },
        "hospital": {
            "did": "ID",
            "name": "مستشفى طرابلس",
            "casualties": {
                "male_deaths": 2,
                "male_injuries": None,
                "female_deaths": 1,
                "female_injuries": None,
                "children_deaths": None,
                "children_injuries": None,
                "deaths": None,
                "injuries": None,
                "total_deaths": None,
                "total_injuries": None,
            },
        },
    }
    db = _SessionStub()
    service = IncidentMaterializationService(db)  # type: ignore[arg-type]
    representative = _representative()
    representative.extraction_result = extraction

    result = service.materialize(representative)

    assert len(result) == 1
    incident = result[0]
    detail = next(value for value in db.committed if isinstance(value, IncidentDetail))
    assert detail.la is True
    assert detail.la_did == "D"
    assert detail.la_td == 1
    assert detail.hosp is True
    assert detail.hos_n == "مستشفى طرابلس"
    assert detail.hosd == 3
    # root deaths=3 + la_td=1 + hosd=3
    assert incident.total_deaths == 7


# ---------------------------------------------------------------------------
# Item 2: per-row pipeline stage timestamps
# ---------------------------------------------------------------------------


def test_full_materialization_sets_materialized_at_only() -> None:
    """Full-path insert stamps materialized_at; fast_path_completed_at stays NULL."""
    db = _SessionStub()
    service = IncidentMaterializationService(db)  # type: ignore[arg-type]
    representative = _representative()

    service.materialize(representative)

    assert representative.status == MessageStatus.materialized
    assert representative.materialized_at is not None
    assert representative.fast_path_completed_at is None


def test_dedup_merge_sets_materialized_at() -> None:
    """Merge-into-existing on the full path still stamps materialized_at."""
    existing = SimpleNamespace(id=uuid4())
    dedup = _DedupServiceStub(existing=existing, score=0.9)  # type: ignore[arg-type]
    db = _SessionStub()
    service = IncidentMaterializationService(db, dedup_service=dedup)  # type: ignore[arg-type]
    representative = _representative()

    service.materialize(representative)

    assert representative.status == MessageStatus.materialized
    assert representative.materialized_at is not None
    assert representative.fast_path_completed_at is None


def test_fast_path_insert_sets_both_timestamps() -> None:
    """Fast-path materialize stamps fast_path_completed_at and materialized_at."""
    db = _SessionStub()
    service = IncidentMaterializationService(db)  # type: ignore[arg-type]
    representative = _representative()

    service.process_fast_path(
        representative,
        SimpleNamespace(
            decide_for_village=lambda **_kwargs: SimpleNamespace(
                outcome=FastPathDedupOutcome.materialize,
                representative_raw_message_id=None,
                canonical_incident_id=None,
            )
        ),
    )

    assert representative.status == MessageStatus.materialized
    assert representative.fast_path_completed_at is not None
    assert representative.materialized_at is not None


def test_fast_path_confident_duplicate_merges_when_score_high() -> None:
    """High-score fast-path duplicate merges into the canonical incident."""
    existing = SimpleNamespace(id=uuid4(), raw_message_id=999)
    dedup = _DedupServiceStub(existing=existing, score=0.85)  # type: ignore[arg-type]
    duplicate_matches: list[dict] = []
    db = _SessionStub()
    service = IncidentMaterializationService(db, dedup_service=dedup)  # type: ignore[arg-type]
    representative = _representative()

    service.process_fast_path(
        representative,
        SimpleNamespace(
            incidents=SimpleNamespace(
                create_fast_path_duplicate_match=lambda **kwargs: duplicate_matches.append(
                    kwargs
                )
            ),
            decide_for_village=lambda **_kwargs: SimpleNamespace(
                outcome=FastPathDedupOutcome.confident_duplicate,
                representative_raw_message_id=999,
                canonical_incident_id=existing.id,
                canonical_incident=existing,
            ),
        ),
    )

    assert len(dedup.merge_calls) == 1
    assert representative.status == MessageStatus.materialized
    assert representative.materialized_at is not None
    assert representative.fast_path_completed_at is not None
    assert len(duplicate_matches) == 1
    assert duplicate_matches[0]["status"].value == "confirmed_duplicate"
    assert duplicate_matches[0]["similarity_score"] == 0.85


def test_fast_path_confident_duplicate_insufficient_score_materializes() -> None:
    """Sub-threshold score keeps a separate incident with insufficient_score audit."""
    existing = SimpleNamespace(id=uuid4(), raw_message_id=999)
    dedup = _DedupServiceStub(existing=existing, score=0.65)  # type: ignore[arg-type]
    duplicate_matches: list[dict] = []
    db = _SessionStub()
    service = IncidentMaterializationService(db, dedup_service=dedup)  # type: ignore[arg-type]
    representative = _representative()

    service.process_fast_path(
        representative,
        SimpleNamespace(
            incidents=SimpleNamespace(
                create_duplicate_match=lambda **kwargs: duplicate_matches.append(
                    kwargs
                )
            ),
            decide_for_village=lambda **_kwargs: SimpleNamespace(
                outcome=FastPathDedupOutcome.confident_duplicate,
                representative_raw_message_id=999,
                canonical_incident_id=existing.id,
                canonical_incident=existing,
            ),
        ),
    )

    assert dedup.merge_calls == []
    assert representative.status == MessageStatus.materialized
    assert representative.materialized_at is not None
    assert representative.fast_path_completed_at is not None
    incident = next(value for value in db.committed if isinstance(value, Incident))
    assert incident.duplicate_flag is True
    assert len(duplicate_matches) == 1
    assert duplicate_matches[0]["incident"] is incident
    assert duplicate_matches[0]["matched_incident"] is existing
    assert duplicate_matches[0]["similarity_score"] == 0.65


def test_terminalized_message_leaves_stage_timestamps_null() -> None:
    """An unmaterializable row gets neither fast_path_completed_at nor materialized_at."""
    db = _SessionStub()
    service = IncidentMaterializationService(db)  # type: ignore[arg-type]
    representative = _representative(
        match_result=_match_result(condition_status="unmatched", condition_id=None)
    )

    service.materialize(representative)

    assert representative.status == MessageStatus.error
    assert representative.fast_path_completed_at is None
    assert representative.materialized_at is None
