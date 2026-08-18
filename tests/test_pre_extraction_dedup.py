"""
Unit tests for sweep_pre_extraction_dedup.

pg_trgm's word_similarity() is a PostgreSQL-only function, so these tests
follow the same stub-session pattern used in test_condition_repository.py:
the DB layer is replaced by a minimal in-process stub, and the SQL query is
never actually executed.  Integration coverage against a real DB can be added
separately (guarded by DATABASE_URL, same as other test files here).
"""
from __future__ import annotations

from types import SimpleNamespace

from app.news.models import MessageStatus
from app.news.services.pipeline_sweep_stages import sweep_pre_extraction_dedup


# ---------------------------------------------------------------------------
# Minimal stubs that mimic the SQLAlchemy Session interface
# ---------------------------------------------------------------------------


class _ScalarsResult:
    def __init__(self, values: list) -> None:
        self._values = values

    def all(self) -> list:
        return self._values


class _ExecuteResult:
    def __init__(self, row) -> None:
        self._row = row

    def first(self):
        return self._row


class _StubSession:
    """
    Minimal SQLAlchemy Session stub for sweep_pre_extraction_dedup.

    The sweep function makes exactly these calls per iteration:
      1. db.scalars(batch_query).all()  – returns the batch of eligible IDs
      2. db.get(RawMessage, id)         – returns the RawMessage object
      3. db.execute(similarity_query).first() – returns best-match row or None
      4. db.commit() / db.rollback()    – recorded as counters
    """

    def __init__(
        self,
        *,
        batch_ids: list[int],
        messages: dict[int, object],
        similarity_result,
    ) -> None:
        self._batch_ids = batch_ids
        self._messages = messages
        self._similarity_result = similarity_result
        self._scalars_call = 0
        self.committed = 0
        self.rolled_back = 0

    def scalars(self, stmt) -> _ScalarsResult:
        self._scalars_call += 1
        # First call: return the batch; subsequent calls: signal end-of-work.
        if self._scalars_call == 1:
            return _ScalarsResult(self._batch_ids)
        return _ScalarsResult([])

    def get(self, model, pk: int):
        return self._messages.get(pk)

    def execute(self, stmt) -> _ExecuteResult:
        return _ExecuteResult(self._similarity_result)

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        self.rolled_back += 1


class _SameBatchStubSession(_StubSession):
    """Returns per-message similarity matches for multi-row batch tests."""

    def __init__(
        self,
        *,
        batch_ids: list[int],
        messages: dict[int, object],
        similarity_targets: dict[int, object],
    ) -> None:
        super().__init__(
            batch_ids=batch_ids,
            messages=messages,
            similarity_result=None,
        )
        self._similarity_targets = similarity_targets
        self._current_message_id: int | None = None

    def get(self, model, pk: int):
        self._current_message_id = pk
        return self._messages.get(pk)

    def execute(self, stmt) -> _ExecuteResult:
        assert self._current_message_id is not None
        return _ExecuteResult(
            self._similarity_targets.get(self._current_message_id)
        )


def _make_msg(
    id_: int,
    raw_text: str = "some news text",
    *,
    status: MessageStatus = MessageStatus.parsed,
) -> SimpleNamespace:
    """Return a SimpleNamespace that behaves like a RawMessage ORM object."""
    return SimpleNamespace(
        id=id_,
        raw_text=raw_text,
        status=status,
        extraction_result=None,
        duplicate_of_id=None,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_near_duplicate_within_window_marked_as_duplicate() -> None:
    """
    When the similarity query finds a match with score >= threshold (0.92),
    the higher-id message should be marked duplicate of the lower-id original.
    """
    msg = _make_msg(100, "غارة جوية على بنت جبيل")
    original = _make_msg(99, "غارة جوية على بنت جبيل")
    session = _StubSession(
        batch_ids=[100],
        messages={100: msg, 99: original},
        similarity_result=SimpleNamespace(id=99, score=0.95),
    )

    result = sweep_pre_extraction_dedup(session)  # type: ignore[arg-type]

    assert result.stage == "pre_extraction_dedup"
    assert result.processed == 1
    assert result.succeeded == 1
    assert result.failed == 0
    assert msg.status == MessageStatus.duplicate
    assert msg.duplicate_of_id == 99
    assert session.committed == 1
    assert session.rolled_back == 0


def test_same_batch_pair_only_higher_id_marked_duplicate() -> None:
    """
    Two near-identical messages in one batch must not both become duplicates.
    The lower id remains parsed; only the higher id points at the lower id.
    """
    lower = _make_msg(711, "غارة جوية على بنت جبيل")
    higher = _make_msg(712, "غارة جوية على بنت جبيل")
    session = _SameBatchStubSession(
        batch_ids=[711, 712],
        messages={711: lower, 712: higher},
        similarity_targets={
            711: SimpleNamespace(id=712, score=0.95),
            712: SimpleNamespace(id=711, score=0.95),
        },
    )

    result = sweep_pre_extraction_dedup(session)  # type: ignore[arg-type]

    assert result.processed == 2
    assert result.succeeded == 1
    assert result.failed == 0
    assert lower.status == MessageStatus.parsed
    assert lower.duplicate_of_id is None
    assert higher.status == MessageStatus.duplicate
    assert higher.duplicate_of_id == 711
    assert session.committed == 1


def test_distinct_message_left_unchanged() -> None:
    """
    When the best similarity score is below threshold (0.92), the message
    should remain status='parsed' and not be flagged as a duplicate.
    """
    msg = _make_msg(2, "خبر لا علاقة له بالأحداث السابقة")
    session = _StubSession(
        batch_ids=[2],
        messages={2: msg},
        similarity_result=SimpleNamespace(id=99, score=0.50),
    )

    result = sweep_pre_extraction_dedup(session)  # type: ignore[arg-type]

    assert result.processed == 1
    assert result.succeeded == 0  # no dedup decision was made
    assert result.failed == 0
    assert msg.status == MessageStatus.parsed
    assert msg.duplicate_of_id is None
    assert session.committed == 0
    assert session.rolled_back == 0


def test_out_of_window_near_duplicate_not_flagged() -> None:
    """
    A near-duplicate that is older than 48 hours is excluded from the
    comparison set by the SQL WHERE clause on received_at.  The stub
    simulates this by returning None from .first() — exactly what the DB
    returns when no row survives the window filter — so the current message
    must not be flagged.
    """
    msg = _make_msg(3, "غارة جوية على بنت جبيل")
    session = _StubSession(
        batch_ids=[3],
        messages={3: msg},
        # DB returned no row because the only near-duplicate is > 48 h old.
        similarity_result=None,
    )

    result = sweep_pre_extraction_dedup(session)  # type: ignore[arg-type]

    assert result.processed == 1
    assert result.succeeded == 0
    assert result.failed == 0
    assert msg.status == MessageStatus.parsed
    assert msg.duplicate_of_id is None
    assert session.committed == 0
    assert session.rolled_back == 0
