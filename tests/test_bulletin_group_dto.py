from datetime import datetime, timezone
from types import SimpleNamespace

from app.news.dtos import BulletinCasualtyGroupDTO
from app.news.models.bulletin_casualty_group import (
    BulletinBreakdownStatus,
    CasualtyScope,
)


def test_bulletin_group_dto_serializes_model_enums() -> None:
    now = datetime.now(timezone.utc)
    group = SimpleNamespace(
        raw_message_id=7,
        village_ids=[10, 20],
        casualty_scope=CasualtyScope.bulletin_aggregate,
        total_deaths=4,
        total_injuries=20,
        breakdown_status=BulletinBreakdownStatus.pending,
        window_expires_at=now,
        resolved_at=None,
        resolved_by_raw_message_id=None,
    )

    payload = BulletinCasualtyGroupDTO.model_validate(group)

    assert payload.casualty_scope == "bulletin_aggregate"
    assert payload.breakdown_status == "pending"
    assert (payload.total_deaths, payload.total_injuries) == (4, 20)
