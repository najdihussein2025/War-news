from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401
from app.news.dtos import IncidentListItemDTO, IncidentListParams
from app.news.models import Incident, IncidentUpdate, MessageStatus, UpdateAction
from app.news.repositories.incident_repository import IncidentRepository
from app.news.services.materialization.verification_signals import (
    LOW_CONFIDENCE_VILLAGE_REVIEW_REASON,
)


def _compiled_filters(filters: list[object]) -> str:
    return " ".join(
        str(filter_.compile(compile_kwargs={"literal_binds": True}))
        for filter_ in filters
    ).lower()


class _ScalarResult:
    def __init__(self, incidents: list[Incident]) -> None:
        self.incidents = incidents

    def all(self) -> list[Incident]:
        return self.incidents


class _SessionStub:
    def __init__(self, incidents: list[Incident]) -> None:
        self.incidents = incidents
        self.added: list[Incident] = []
        self.flush_calls = 0

    def scalars(self, _statement) -> _ScalarResult:
        return _ScalarResult(self.incidents)

    def add(self, incident: Incident) -> None:
        self.added.append(incident)

    def flush(self) -> None:
        self.flush_calls += 1


def test_pipeline_duplicate_for_raw_message_id_retires_incident() -> None:
    incident = Incident()
    incident.id = uuid4()
    incident.is_deleted = False
    db = _SessionStub([incident])

    deleted_ids = IncidentRepository(db).soft_delete_for_raw_message_id(42)  # type: ignore[arg-type]

    assert deleted_ids == [incident.id]
    assert incident.is_deleted is True
    assert incident.duplicate_flag is False
    assert db.added[-1] is incident
    [audit] = [row for row in db.added if isinstance(row, IncidentUpdate)]
    assert audit.action == UpdateAction.delete
    assert audit.new_values["deleted_reason"] == "cluster_subsumption"
    assert db.flush_calls == 1


def test_toll_revisions_hide_noop_and_preserve_source_attribution() -> None:
    incident_id = uuid4()
    timestamp = datetime.now(timezone.utc)
    no_op = IncidentUpdate(
        incident_id=incident_id,
        action=UpdateAction.pipeline_merge,
        old_values={"deaths": None, "injuries": None},
        new_values={
            "story_revision": True,
            "deaths": None,
            "injuries": None,
            "merged_from": {"raw_message_id": 1},
        },
        created_at=timestamp,
    )
    changed = IncidentUpdate(
        incident_id=incident_id,
        action=UpdateAction.pipeline_merge,
        old_values={"deaths": None, "injuries": None},
        new_values={
            "story_revision": True,
            "deaths": 1,
            "injuries": None,
            "merged_from": {
                "raw_message_id": 9298,
                "channel": "newtv",
                "khabar": "شهيد في زبدين",
            },
        },
        created_at=timestamp,
    )
    db = _SessionStub([no_op, changed])

    revisions = IncidentRepository(db)._toll_revisions_for(incident_id)  # type: ignore[arg-type]

    assert len(revisions) == 1
    assert revisions[0].new_deaths == 1
    assert revisions[0].source_raw_message_id == 9298
    assert revisions[0].source_channel == "newtv"
    assert revisions[0].source_khabar == "شهيد في زبدين"


def test_toll_revision_ignores_malformed_merged_from_payload() -> None:
    incident_id = uuid4()
    update = IncidentUpdate(
        incident_id=incident_id,
        action=UpdateAction.pipeline_merge,
        old_values={"deaths": None},
        new_values={
            "story_revision": True,
            "deaths": 1,
            "merged_from": "legacy",
        },
        created_at=datetime.now(timezone.utc),
    )

    revisions = IncidentRepository(_SessionStub([update]))._toll_revisions_for(  # type: ignore[arg-type]
        incident_id
    )

    assert revisions[0].source_raw_message_id is None


def test_pipeline_duplicate_for_raw_message_id_is_idempotent() -> None:
    db = _SessionStub([])

    deleted_ids = IncidentRepository(db).soft_delete_for_raw_message_id(42)  # type: ignore[arg-type]

    assert deleted_ids == []
    assert db.added == []
    assert db.flush_calls == 1


def test_mark_raw_duplicate_flattens_existing_child_links() -> None:
    raw = SimpleNamespace(
        id=22,
        status=MessageStatus.materialized,
        duplicate_of_id=None,
        error_message=None,
    )
    canonical = SimpleNamespace(id=11, duplicate_of_id=None)
    child = SimpleNamespace(id=33, duplicate_of_id=22)
    db = MagicMock()
    db.get.side_effect = lambda _model, raw_id: {
        11: canonical,
        22: raw,
    }.get(raw_id)
    db.scalars.return_value.all.return_value = [child]
    repository = IncidentRepository(db)
    repository.has_active_incidents_for_raw_message = lambda _raw_id: False  # type: ignore[method-assign]

    changed = repository.mark_raw_duplicate_if_fully_subsumed(
        raw_message_id=22,
        canonical_raw_message_id=11,
    )

    assert changed is True
    assert raw.status == MessageStatus.duplicate
    assert raw.duplicate_of_id == 11
    assert child.duplicate_of_id == 11


class _ListResult:
    def __init__(self, casualties_count: int = 0) -> None:
        self.casualties_count = casualties_count

    def all(self) -> list[object]:
        return []

    def one(self) -> object:
        return type(
            "Summary",
            (),
            {
                "needs_verification_count": 0,
                "casualties_count": self.casualties_count,
            },
        )()


class _ListSessionStub:
    def __init__(self, casualties_count: int = 0) -> None:
        self.statements: list[object] = []
        self.casualties_count = casualties_count

    def execute(self, statement: object) -> _ListResult:
        self.statements.append(statement)
        return _ListResult(self.casualties_count)

    def scalar(self, _statement: object) -> int:
        return 0


class _VerificationSessionStub:
    def __init__(self, incident: object, raw_message: object) -> None:
        self.results = iter([incident, raw_message])
        self.added: list[object] = []
        self.committed = False

    def scalar(self, _statement: object) -> object:
        # Third query is the per-incident reject sibling check: no other live
        # village incident, so the raw message itself moves to Rejected News.
        return next(self.results, None)

    def add(self, value: object) -> None:
        self.added.append(value)

    def commit(self) -> None:
        self.committed = True


def test_rejecting_incident_moves_raw_message_to_rejected_news() -> None:
    incident_id = uuid4()
    user_id = uuid4()
    incident = SimpleNamespace(
        id=incident_id,
        raw_message_id=42,
        verification_status="needs_verification",
        verification_reason=None,
        verified_by_user_id=None,
        verified_at=None,
    )
    raw_message = SimpleNamespace(
        filter_result={"existing": "value"},
        status=MessageStatus.materialized,
        error_message=None,
    )
    db = _VerificationSessionStub(incident, raw_message)
    repository = IncidentRepository(db)  # type: ignore[arg-type]
    repository.get_by_id = lambda _incident_id: SimpleNamespace(id=incident_id)  # type: ignore[method-assign]

    repository.set_verification(
        incident_id,
        "rejected",
        "Not a valid incident",
        1,
        user_id,
    )

    assert incident.verification_status == "rejected"
    assert raw_message.status == MessageStatus.rejected
    assert raw_message.error_message == "Not a valid incident"
    assert raw_message.filter_result == {
        "existing": "value",
        "verdict": "reject",
        "reasoning": "Not a valid incident",
        "review_source": "human",
        "reviewed_by_user_id": str(user_id),
    }
    assert db.committed is True


def test_list_all_defaults_to_newest_event_first() -> None:
    db = _ListSessionStub()

    IncidentRepository(db).list_all(IncidentListParams())  # type: ignore[arg-type]

    compiled = str(
        db.statements[0].compile(compile_kwargs={"literal_binds": True})
    ).lower()
    order_at = compiled.index("order by")
    created_at = compiled.index(
        "coalesce(incidents.created_at, raw_messages.received_at)",
        order_at,
    )
    event_date_at = compiled.index("incidents.event_date", order_at)
    assert event_date_at < created_at
    assert "coalesce(incidents.event_date" in compiled


def test_list_all_starts_from_incidents_and_requires_materialized_raw_message() -> None:
    db = _ListSessionStub()

    IncidentRepository(db).list_all(IncidentListParams())  # type: ignore[arg-type]

    compiled = str(
        db.statements[0].compile(compile_kwargs={"literal_binds": True})
    ).lower()
    assert "from incidents left outer join raw_messages" in compiled
    assert "incidents.is_deleted is false" in compiled
    assert "raw_messages.id is not null" in compiled
    assert "raw_messages.status = 'materialized'" in compiled


def test_list_all_excludes_ocr_payload_rows() -> None:
    db = _ListSessionStub()

    IncidentRepository(db).list_all(IncidentListParams())  # type: ignore[arg-type]

    compiled = str(
        db.statements[0].compile(compile_kwargs={"literal_binds": True})
    ).lower()
    assert "not (raw_messages.raw_payload ? 'ocr_text')" in compiled


def test_list_all_excludes_non_materialized_raw_message_rows() -> None:
    db = _ListSessionStub()

    IncidentRepository(db).list_all(IncidentListParams())  # type: ignore[arg-type]

    compiled = str(
        db.statements[0].compile(compile_kwargs={"literal_binds": True})
    ).lower()
    assert "raw_messages.status = 'materialized'" in compiled


def test_list_all_incident_scoped_filters_require_active_incident() -> None:
    db = _ListSessionStub()

    IncidentRepository(db).list_all(  # type: ignore[arg-type]
        IncidentListParams(village="Aitaroun")
    )

    compiled = str(
        db.statements[0].compile(compile_kwargs={"literal_binds": True})
    ).lower()
    assert "incidents.is_deleted is false" in compiled


def test_list_all_uses_keyset_filter_without_offset() -> None:
    db = _ListSessionStub()
    repository = IncidentRepository(db)  # type: ignore[arg-type]
    cursor = repository._encode_list_cursor(
        {
            "created_at": datetime(2026, 8, 28, 9, 30, tzinfo=timezone.utc),
            "event_date": date(2026, 8, 28),
            "event_time": None,
            "raw_message_id": 42,
            "id": None,
        }
    )

    repository.list_all(IncidentListParams(cursor=cursor))

    compiled = str(
        db.statements[0].compile(compile_kwargs={"literal_binds": True})
    ).lower()
    assert "offset" not in compiled
    assert "coalesce(raw_messages.id, 0) < 42" in compiled
    assert "coalesce(raw_messages.id, 0) desc, incidents.id desc nulls last" in compiled


def test_list_all_cursor_supports_excel_incident_without_raw_message() -> None:
    db = _ListSessionStub()
    repository = IncidentRepository(db)  # type: ignore[arg-type]
    cursor = repository._encode_list_cursor(
        {
            "created_at": datetime(2026, 9, 3, 6, 24, tzinfo=timezone.utc),
            "event_date": date(2026, 8, 14),
            "event_time": None,
            "raw_message_id": None,
            "id": uuid4(),
        }
    )

    repository.list_all(IncidentListParams(cursor=cursor))

    compiled = str(
        db.statements[0].compile(compile_kwargs={"literal_binds": True})
    ).lower()
    assert "coalesce(raw_messages.id, 0)" in compiled


def test_incident_list_item_accepts_pre_materialization_row() -> None:
    item = IncidentListItemDTO.model_validate(
        {
            "id": None,
            "raw_message_id": 42,
            "raw_status": "parsed",
            "village": None,
            "condition": None,
            "event_date": date(2026, 8, 28),
            "event_time": None,
            "khabar": "Incoming report still in processing.",
            "source": "Telegram",
            "source_reference": "source-channel",
            "matched": False,
            "duplicate_flag": "none",
            "details_pending": True,
            "created_at": datetime(2026, 8, 28, 9, 30, tzinfo=timezone.utc),
            "version": 1,
            "locked_by_user_id": None,
            "edit_lock_expires_at": None,
        }
    )

    assert item.id is None
    assert item.raw_message_id == 42
    assert item.raw_status == "parsed"


def test_incident_list_item_accepts_excel_import_without_raw_message() -> None:
    item = IncidentListItemDTO.model_validate(
        {
            "id": uuid4(),
            "raw_message_id": None,
            "raw_status": None,
            "village": "Kfar Chouba",
            "condition": "Artillery Shelling",
            "event_date": date(2026, 8, 14),
            "event_time": None,
            "khabar": "Imported workbook incident",
            "source": None,
            "source_reference": None,
            "matched": True,
            "duplicate_flag": "none",
            "details_pending": False,
            "created_at": datetime(2026, 9, 3, 6, 24, tzinfo=timezone.utc),
            "version": 1,
            "locked_by_user_id": None,
            "edit_lock_expires_at": None,
        }
    )

    assert item.raw_message_id is None
    assert item.raw_status is None


def test_incident_list_item_accepts_story_group_and_village_id() -> None:
    group_id = uuid4()
    item = IncidentListItemDTO.model_validate(
        {
            "id": uuid4(),
            "raw_message_id": 42,
            "raw_status": "materialized",
            "village": "Kfar Roummane",
            "condition": "Bombs",
            "event_date": date(2026, 9, 7),
            "khabar": "غارة على منزل",
            "source": "Telegram",
            "source_reference": "channel",
            "matched": True,
            "duplicate_flag": "none",
            "details_pending": False,
            "created_at": datetime(2026, 9, 7, 11, 33, tzinfo=timezone.utc),
            "village_id": 851,
            "story_group_id": group_id,
        }
    )

    assert item.village_id == 851
    assert item.story_group_id == group_id


def test_list_filters_needs_verification_uses_duplicate_review_only() -> None:
    filters = IncidentRepository._list_filters(
        IncidentListParams(verification_status="needs_verification")
    )
    compiled = _compiled_filters(filters)
    assert "incidents.verification_status" in compiled
    assert "incidents.duplicate_flag" in compiled
    assert "low-confidence village match requires manual review" not in compiled
    assert "category casualties" not in compiled
    assert "unsupported casualty_scope" not in compiled
    assert "any_village_low_confidence" not in compiled
    assert "match_result" not in compiled


def test_list_filters_hide_rejected_but_keep_needs_verification_by_default() -> None:
    default_filters = IncidentRepository._list_filters(IncidentListParams())
    rejected_filters = IncidentRepository._list_filters(
        IncidentListParams(verification_status="rejected")
    )

    assert "incidents.verification_status != " in " ".join(
        str(filter_) for filter_ in default_filters
    ).lower()
    assert "low-confidence village match requires manual review" not in _compiled_filters(default_filters)
    assert "incidents.verification_status = " in " ".join(
        str(filter_) for filter_ in rejected_filters
    ).lower()


def test_list_filters_exclude_air_violation_conditions() -> None:
    filters = IncidentRepository._list_filters(IncidentListParams())
    compiled = _compiled_filters(filters)

    assert "incidents.condition_id" in compiled
    assert "35" in compiled
    assert "36" in compiled
    assert "38" in compiled


def test_list_filters_hide_ordinary_burning_properties_incidents() -> None:
    filters = IncidentRepository._list_filters(IncidentListParams())
    compiled = _compiled_filters(filters)

    assert "burning properties" in compiled
    assert "incidents.khabar" in compiled
    assert "raw_messages.raw_text" in compiled
    assert "israel" in compiled
    assert "قصف" in compiled


def test_list_filters_hide_palestine_only_incidents() -> None:
    filters = IncidentRepository._list_filters(IncidentListParams())
    compiled = _compiled_filters(filters)

    assert "ramallah" in compiled
    assert "gaza" in compiled
    assert "رام الله" in compiled
    assert "غزة" in compiled
    assert "lebanon" in compiled
    assert "لبنان" in compiled


def test_user_visible_needs_verification_requires_duplicate_flag() -> None:
    incident = Incident()
    incident.verification_status = "needs_verification"
    incident.duplicate_flag = True
    incident.verification_reason = None

    assert IncidentRepository._is_user_visible_needs_verification(incident)


def test_user_visible_needs_verification_excludes_low_confidence_village_reason() -> None:
    incident = Incident()
    incident.verification_status = "needs_verification"
    incident.duplicate_flag = False
    incident.verification_reason = LOW_CONFIDENCE_VILLAGE_REVIEW_REASON

    assert not IncidentRepository._is_user_visible_needs_verification(incident)
    assert not IncidentRepository._should_keep_needs_verification_after_duplicate_clear(incident.verification_reason)


def test_user_visible_needs_verification_hides_stale_unreasoned_nv() -> None:
    incident = Incident()
    incident.verification_status = "needs_verification"
    incident.duplicate_flag = False
    incident.verification_reason = None

    assert not IncidentRepository._is_user_visible_needs_verification(incident)


def test_list_filters_matched_alias_excludes_needs_verification_column() -> None:
    # "matched" is a legacy filter alias handled in _list_filters.
    params = IncidentListParams.model_construct(verification_status="matched")
    filters = IncidentRepository._list_filters(params)
    compiled = " ".join(str(f) for f in filters).lower()
    assert "incidents.verification_status" in compiled
    assert "any_village_low_confidence" not in compiled
    assert "match_result" not in compiled


def test_list_filters_by_raw_message_source_name() -> None:
    filters = IncidentRepository._list_filters(
        IncidentListParams(source_name="Al Jadeed")
    )
    compiled = " ".join(str(f) for f in filters).lower()
    assert "raw_messages.source_name" in compiled


def test_list_filters_has_casualties_uses_rollup_fields() -> None:
    filters = IncidentRepository._list_filters(
        IncidentListParams(has_casualties=True)
    )
    compiled = " ".join(str(filter_) for filter_ in filters).lower()
    assert "coalesce(incidents.total_deaths" in compiled
    assert "coalesce(incidents.total_injuries" in compiled
    assert "> " in compiled


def test_list_all_returns_casualties_summary_count() -> None:
    db = _ListSessionStub(casualties_count=2)

    result = IncidentRepository(db).list_all(  # type: ignore[arg-type]
        IncidentListParams()
    )

    assert result.casualties_count == 2
    summary_sql = str(
        db.statements[-1].compile(compile_kwargs={"literal_binds": True})
    ).lower()
    assert "coalesce(incidents.total_deaths, 0) > 0" in summary_sql
    assert "coalesce(incidents.total_injuries, 0) > 0" in summary_sql



def test_list_duplicate_candidates_excludes_same_raw_message_when_requested() -> None:
    db = _ListSessionStub()

    IncidentRepository(db).list_duplicate_candidates(  # type: ignore[arg-type]
        village_id=976,
        event_date=date(2026, 8, 28),
        khabar_embedding=[0.1, 0.2, 0.3],
        window_days=2,
        exclude_raw_message_id=42,
    )

    compiled = str(
        db.statements[0].compile(compile_kwargs={"literal_binds": True})
    ).lower()
    assert "incidents.village_id = 976" in compiled
    assert "incidents.raw_message_id != 42" in compiled
