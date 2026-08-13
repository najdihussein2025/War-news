from app.actions.news import ListSourcesAction
from app.models.news import Source, SourceType


class _SourceRepository:
    def list_all(self) -> list[Source]:
        return [
            Source(
                id=1,
                type=SourceType.api,
                name="CNRS Inspected Posts",
                is_active=True,
            ),
            Source(
                id=2,
                type=SourceType.api,
                name="CNRS Inspected Posts (LLM)",
                is_active=True,
            ),
        ]


def test_list_sources_returns_only_list_fields() -> None:
    result = ListSourcesAction(_SourceRepository()).execute()  # type: ignore[arg-type]

    assert [item.model_dump(mode="json") for item in result] == [
        {
            "id": 1,
            "type": "api",
            "name": "CNRS Inspected Posts",
            "is_active": True,
        },
        {
            "id": 2,
            "type": "api",
            "name": "CNRS Inspected Posts (LLM)",
            "is_active": True,
        },
    ]
