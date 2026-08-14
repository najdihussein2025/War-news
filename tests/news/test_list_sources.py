from datetime import datetime, timezone

import pytest

from app.sources.actions import (
    GetSourceAction,
    ListSourcesAction,
    SetSourceActiveAction,
    SourceNotFoundError,
)
from app.sources.dtos import (
    SourceActiveUpdateData,
    SourceDetailDTO,
    SourceListItemDTO,
    SourceLookupData,
)
from app.sources.models import SourceType


class _SourceRepository:
    def __init__(self) -> None:
        self.source = SourceDetailDTO(
            id=1,
            type=SourceType.api,
            name="CNRS Inspected Posts",
            is_active=True,
            last_message_at=datetime(2026, 8, 14, 8, 30, tzinfo=timezone.utc),
            total_messages=12,
            external_id="cnrs-posts",
            created_at=datetime(2026, 8, 11, 7, 0, tzinfo=timezone.utc),
            last_cursor="page-12",
        )

    def list_all(self) -> list[SourceListItemDTO]:
        return [
            SourceListItemDTO(
                id=1,
                type=SourceType.api,
                name="CNRS Inspected Posts",
                is_active=True,
                last_message_at=datetime(2026, 8, 14, 8, 30, tzinfo=timezone.utc),
                total_messages=12,
            ),
            SourceListItemDTO(
                id=2,
                type=SourceType.api,
                name="CNRS Inspected Posts (LLM)",
                is_active=False,
                last_message_at=None,
                total_messages=0,
            ),
        ]

    def get_detail(self, source_id: int) -> SourceDetailDTO | None:
        return self.source if source_id == self.source.id else None

    def set_active(
        self,
        source_id: int,
        is_active: bool,
    ) -> SourceDetailDTO | None:
        if source_id != self.source.id:
            return None
        self.source = self.source.model_copy(update={"is_active": is_active})
        return self.source


def test_list_sources_returns_table_fields() -> None:
    result = ListSourcesAction(_SourceRepository()).execute()  # type: ignore[arg-type]

    assert [item.model_dump(mode="json") for item in result] == [
        {
            "id": 1,
            "type": "api",
            "name": "CNRS Inspected Posts",
            "is_active": True,
            "last_message_at": "2026-08-14T08:30:00Z",
            "total_messages": 12,
        },
        {
            "id": 2,
            "type": "api",
            "name": "CNRS Inspected Posts (LLM)",
            "is_active": False,
            "last_message_at": None,
            "total_messages": 0,
        },
    ]


def test_get_source_returns_debug_detail() -> None:
    result = GetSourceAction(_SourceRepository()).execute(SourceLookupData(source_id=1))

    assert result.external_id == "cnrs-posts"
    assert result.last_cursor == "page-12"
    assert result.total_messages == 12


def test_set_source_active_toggles_state() -> None:
    repository = _SourceRepository()

    paused = SetSourceActiveAction(repository).execute(
        SourceActiveUpdateData(source_id=1, is_active=False)
    )
    resumed = SetSourceActiveAction(repository).execute(
        SourceActiveUpdateData(source_id=1, is_active=True)
    )

    assert paused.is_active is False
    assert resumed.is_active is True


def test_source_actions_raise_for_unknown_source() -> None:
    repository = _SourceRepository()

    with pytest.raises(SourceNotFoundError):
        GetSourceAction(repository).execute(SourceLookupData(source_id=99))

    with pytest.raises(SourceNotFoundError):
        SetSourceActiveAction(repository).execute(
            SourceActiveUpdateData(source_id=99, is_active=False)
        )
