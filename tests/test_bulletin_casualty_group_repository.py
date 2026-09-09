from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.news.models.bulletin_casualty_group import (
    BulletinBreakdownStatus,
    CasualtyScope,
)
from app.news.repositories.bulletin_casualty_group_repository import (
    BulletinCasualtyGroupRepository,
)


def test_create_for_message_refreshes_existing_unresolved_totals() -> None:
    db = MagicMock()
    existing = SimpleNamespace(
        village_ids=[10],
        casualty_scope=CasualtyScope.unspecified,
        total_deaths=None,
        total_injuries=None,
        breakdown_status=BulletinBreakdownStatus.n_a,
        window_expires_at=None,
        updated_at=None,
    )
    repository = BulletinCasualtyGroupRepository(db)
    repository.get_by_raw_message_id = MagicMock(return_value=existing)  # type: ignore[method-assign]
    now = datetime.now(timezone.utc)

    result = repository.create_for_message(
        raw_message_id=7,
        village_ids=[20, 10, 20],
        casualty_scope=CasualtyScope.bulletin_aggregate,
        total_deaths=4,
        total_injuries=20,
        created_at=now,
    )

    assert result is existing
    assert existing.village_ids == [10, 20]
    assert (existing.total_deaths, existing.total_injuries) == (4, 20)
    assert existing.breakdown_status == BulletinBreakdownStatus.pending
    assert existing.window_expires_at is not None
    db.add.assert_called_once_with(existing)
    db.flush.assert_called_once()
