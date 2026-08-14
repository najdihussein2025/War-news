from datetime import datetime, timezone

from app.actions.news import ListContentSourcesAction
from app.dtos.news import ContentSourceFilterData, ContentSourceListItemDTO


class _ContentSourceRepository:
    def __init__(self) -> None:
        self.filters: ContentSourceFilterData | None = None

    def list_all(
        self,
        filters: ContentSourceFilterData,
    ) -> list[ContentSourceListItemDTO]:
        self.filters = filters
        return [
            ContentSourceListItemDTO(
                source_platform="twitter",
                source_name="annahar",
                message_count=42,
                last_seen=datetime(2026, 8, 14, 9, 15, tzinfo=timezone.utc),
            )
        ]


def test_list_content_sources_returns_aggregate_rows() -> None:
    result = ListContentSourcesAction(_ContentSourceRepository()).execute(
        ContentSourceFilterData()
    )

    assert [item.model_dump(mode="json") for item in result] == [
        {
            "source_platform": "twitter",
            "source_name": "annahar",
            "message_count": 42,
            "last_seen": "2026-08-14T09:15:00Z",
        }
    ]


def test_list_content_sources_passes_filters_to_repository() -> None:
    repository = _ContentSourceRepository()
    filters = ContentSourceFilterData(platform="twitter", search="mtv")

    ListContentSourcesAction(repository).execute(filters)

    assert repository.filters == filters
