from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from app.llm.dtos import (
    CasualtyScope,
    ExtractionResult,
    VillageRole,
    VillageRoleEntry,
)
from app.news.models import IncidentUpdate
from app.news.models.bulletin_casualty_group import BulletinBreakdownStatus
from app.news.services.reconciliation import BulletinReconciliationService


def _group(*, group_id: int = 5) -> SimpleNamespace:
    return SimpleNamespace(
        id=group_id,
        raw_message_id=11,
        village_ids=[10, 20],
        breakdown_status=BulletinBreakdownStatus.pending,
    )


def _candidate() -> SimpleNamespace:
    evidence = "سقط شهيدان في النبطية بعد غارات شملت النبطية وكفررمان"
    extraction = ExtractionResult(
        is_relevant=True,
        village=["النبطية", "كفررمان"],
        village_roles=[
            VillageRoleEntry(
                village="النبطية",
                role=VillageRole.target,
                deaths=2,
                evidence_span="سقط شهيدان في النبطية",
            ),
            VillageRoleEntry(village="كفررمان", role=VillageRole.target),
        ],
        casualty_scope=CasualtyScope.per_village_exact,
        casualty_scope_evidence=evidence,
        model="test",
        extracted_at=datetime.now(timezone.utc),
    )
    return SimpleNamespace(
        id=22,
        extraction_result=extraction.model_dump(mode="json"),
        match_result={
            "village_matches": [
                {
                    "matched_village_id": 10,
                    "village_role": "target",
                    "deaths": 2,
                    "injuries": None,
                },
                {
                    "matched_village_id": 20,
                    "village_role": "target",
                    "deaths": None,
                    "injuries": None,
                },
            ]
        },
    )


def test_pending_group_resolves_from_qualifying_follow_up() -> None:
    now = datetime.now(timezone.utc)
    group = _group()
    candidate = _candidate()
    db = MagicMock()
    db.get.return_value = group
    groups = MagicMock()
    groups.list_expiring_groups.return_value = []
    groups.list_open_groups.return_value = [group]
    service = BulletinReconciliationService(db, groups=groups)
    service._find_candidate = MagicMock(return_value=candidate)  # type: ignore[method-assign]
    service._apply_candidate = MagicMock()  # type: ignore[method-assign]

    summary = service.run_once(as_of=now)

    assert summary == {
        "processed": 1,
        "succeeded": 1,
        "failed": 0,
        "expired": 0,
        "resolved": 1,
        "pending": 0,
    }
    service._apply_candidate.assert_called_once_with(
        group,
        candidate,
        resolved_at=now,
    )


def test_pending_group_expires_without_numeric_changes() -> None:
    now = datetime.now(timezone.utc)
    group = _group()
    db = MagicMock()
    db.get.return_value = group
    groups = MagicMock()
    groups.list_expiring_groups.return_value = [group]
    groups.list_open_groups.return_value = []
    service = BulletinReconciliationService(db, groups=groups)

    summary = service.run_once(as_of=now)

    assert summary["expired"] == 1
    assert summary["failed"] == 0
    groups.mark_expired.assert_called_once_with(group, expired_at=now)


def test_candidate_requires_configured_full_village_overlap() -> None:
    origin_time = datetime.now(timezone.utc) - timedelta(hours=1)
    origin = SimpleNamespace(id=11, message_datetime=origin_time)
    candidate = _candidate()
    db = MagicMock()
    db.get.return_value = origin
    db.scalars.return_value.all.return_value = [candidate]
    service = BulletinReconciliationService(db, groups=MagicMock())

    assert service._find_candidate(_group()) is candidate

    candidate.match_result["village_matches"] = candidate.match_result[
        "village_matches"
    ][:1]
    assert service._find_candidate(_group()) is None


def test_applying_same_candidate_twice_does_not_duplicate_update() -> None:
    group = _group()
    candidate = _candidate()
    incident = SimpleNamespace(
        id=uuid4(),
        raw_message_id=11,
        village_id=10,
        deaths=None,
        injuries=None,
        is_deleted=False,
    )
    db = MagicMock()
    stored_updates: list[IncidentUpdate] = []

    def scalars(_statement):
        result = MagicMock()
        call_index = scalars.call_count
        scalars.call_count += 1
        result.all.return_value = [incident] if call_index % 2 == 0 else stored_updates
        return result

    scalars.call_count = 0
    db.scalars.side_effect = scalars

    def add(value):
        if isinstance(value, IncidentUpdate):
            stored_updates.append(value)

    db.add.side_effect = add
    service = BulletinReconciliationService(db, groups=MagicMock())

    service._apply_candidate(group, candidate, resolved_at=datetime.now(timezone.utc))
    service._apply_candidate(group, candidate, resolved_at=datetime.now(timezone.utc))

    assert (incident.deaths, incident.injuries) == (2, None)
    assert len(stored_updates) == 1
