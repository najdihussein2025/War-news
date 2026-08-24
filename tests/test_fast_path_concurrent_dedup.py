from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.llm.dtos import ExtractionCasualties, ExtractionResult
from app.news.models import DuplicateMatch, Incident, MatchType, MessageStatus
from app.news.services.fast_path_dedup import FastPathDedupService
from app.news.services.incident_materialization_service import (
    IncidentMaterializationService,
)


def _match_result() -> dict:
    return {
        "matched_condition_id": 7,
        "condition_match_status": "matched",
        "village_matches": [
            {
                "matched_village_id": 42,
                "village_match_status": "matched",
            }
        ],
    }


def _raw_message(*, message_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=message_id,
        status=MessageStatus.parsed,
        duplicate_of_id=None,
        raw_text="قصف على بلدة",
        source_id=1,
        message_datetime=datetime(2026, 8, 18, 11, 0, tzinfo=timezone.utc),
        extraction_result=ExtractionResult(
            is_relevant=True,
            village=["كفركلا"],
            action_description="قصف",
            casualties=ExtractionCasualties(deaths=1),
            model="test",
            extracted_at=datetime(2026, 8, 18, 11, 0, tzinfo=timezone.utc),
            extraction_tier=1,
        ).model_dump(mode="json"),
        match_result=_match_result(),
        content_embedding=None,
    )


class _SharedStore:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.village_locks: dict[tuple[int, int], threading.Lock] = {}
        self.incidents: list[Incident] = []
        self.duplicate_matches: list[DuplicateMatch] = []

    def village_lock(self, village_id: int, condition_id: int) -> threading.Lock:
        with self.lock:
            return self.village_locks.setdefault(
                (village_id, condition_id),
                threading.Lock(),
            )


class _ConcurrentSession:
    def __init__(self, store: _SharedStore) -> None:
        self.store = store
        self.staged: list[object] = []
        self.held: list[threading.Lock] = []

    def execute(self, _statement, params=None):
        params = params or {}
        village_id = params.get("village_id")
        condition_id = params.get("condition_id")
        if village_id is not None and condition_id is not None:
            lock = self.store.village_lock(int(village_id), int(condition_id))
            lock.acquire()
            self.held.append(lock)
        return SimpleNamespace()

    def add(self, value: object) -> None:
        self.staged.append(value)

    def flush(self) -> None:
        for value in self.staged:
            if isinstance(value, Incident) and getattr(value, "id", None) is None:
                value.id = uuid4()

    def commit(self) -> None:
        with self.store.lock:
            for value in self.staged:
                if isinstance(value, Incident):
                    self.store.incidents.append(value)
                elif isinstance(value, DuplicateMatch):
                    self.store.duplicate_matches.append(value)
            self.staged.clear()
        self._release_locks()

    def rollback(self) -> None:
        self.staged.clear()
        self._release_locks()

    def _release_locks(self) -> None:
        for lock in self.held:
            lock.release()
        self.held.clear()


class _ConcurrentIncidentRepo:
    def __init__(self, store: _SharedStore, session: _ConcurrentSession) -> None:
        self.store = store
        self.db = session

    def find_active_incident_in_fast_dedup_window(self, **kwargs):
        # Hold the advisory lock during the check so the second worker cannot
        # observe a half-written window.
        time.sleep(0.05)
        with self.store.lock:
            for incident in self.store.incidents:
                if (
                    incident.village_id == kwargs["village_id"]
                    and incident.condition_id == kwargs["condition_id"]
                    and not incident.is_deleted
                ):
                    return incident
        return None

    def create_fast_path_duplicate_match(self, *, canonical_incident, raw_message_id: int) -> None:
        self.db.add(
            DuplicateMatch(
                incident_id=canonical_incident.id,
                matched_incident_id=None,
                raw_message_id=raw_message_id,
                match_type=MatchType.exact,
            )
        )
        self.db.flush()


def test_concurrent_fast_path_workers_create_one_incident_and_one_duplicate_match() -> None:
    store = _SharedStore()
    errors: list[BaseException] = []

    def _run(message_id: int) -> None:
        try:
            session = _ConcurrentSession(store)
            service = IncidentMaterializationService(session)  # type: ignore[arg-type]
            dedup = FastPathDedupService(_ConcurrentIncidentRepo(store, session))  # type: ignore[arg-type]
            service.process_fast_path(_raw_message(message_id=message_id), dedup)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    workers = [
        threading.Thread(target=_run, args=(message_id,))
        for message_id in (101, 202)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=5)
        assert not worker.is_alive()

    assert errors == []
    assert len(store.incidents) == 1
    assert len(store.duplicate_matches) == 1
    match = store.duplicate_matches[0]
    assert match.incident_id == store.incidents[0].id
    assert match.matched_incident_id is None
    assert match.raw_message_id in {101, 202}
    assert match.match_type == MatchType.exact
