from datetime import datetime, timezone
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from app.accounts.models import User  # noqa: F401
from app.news.models import RawMessage
from app.sources.actions import ListContentSourcesAction
from app.sources.dtos import (
    ContentSourceFilterData,
    ContentSourceListItemDTO,
)
from app.sources.models import Source, SourceType
from app.sources.repositories.content_source_repository import ContentSourceRepository


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
                origin_account="annahar",
                message_count=42,
                last_seen=datetime(2026, 8, 14, 9, 15, tzinfo=timezone.utc),
                first_seen=datetime(2026, 8, 10, 9, 15, tzinfo=timezone.utc),
                is_blocked=False,
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
            "origin_account": "annahar",
            "message_count": 42,
            "last_seen": "2026-08-14T09:15:00Z",
            "first_seen": "2026-08-10T09:15:00Z",
            "is_blocked": False,
        }
    ]


def test_list_content_sources_passes_filters_to_repository() -> None:
    repository = _ContentSourceRepository()
    filters = ContentSourceFilterData(platform="twitter", search="mtv")

    ListContentSourcesAction(repository).execute(filters)

    assert repository.filters == filters


def test_repository_filters_generic_cnrs_rows_from_mixed_source_batch() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for repository integration coverage.")

    engine = create_engine(database_url)
    marker = uuid4().hex
    platform = f"test-mixed-{marker}"
    real_sources = [f"LBCI_NEWS_{marker}", f"MTVLebanonNews_{marker}"]

    try:
        connection = engine.connect()
    except OperationalError as exc:
        pytest.skip(f"Database is unavailable: {exc}")

    transaction = connection.begin()
    db = Session(bind=connection)
    try:
        source = Source(type=SourceType.api, name=f"CNRS test {marker}", config={})
        db.add(source)
        db.flush()

        received_at = datetime(2026, 8, 14, 9, 0, tzinfo=timezone.utc)
        for index in range(113):
            db.add(
                RawMessage(
                    source_id=source.id,
                    external_message_id=f"{marker}-generic-{index}",
                    source_platform=platform,
                    source_name="CNRS Webhook",
                    origin_account="CNRS Webhook",
                    raw_payload={},
                    received_at=received_at,
                )
            )
        for source_name in real_sources:
            db.add(
                RawMessage(
                    source_id=source.id,
                    external_message_id=f"{marker}-{source_name}",
                    source_platform=platform,
                    source_name=source_name,
                    origin_account=source_name,
                    raw_payload={},
                    received_at=received_at,
                )
            )

        db.flush()

        result = ContentSourceRepository(db).list_all(
            ContentSourceFilterData(platform=platform)
        )

        assert [item.source_name for item in result] == sorted(real_sources)
        assert {item.message_count for item in result} == {1}
        assert "CNRS Webhook" not in {item.source_name for item in result}
    except (OperationalError, ProgrammingError) as exc:
        pytest.skip(f"Content source schema is unavailable: {exc}")
    finally:
        db.close()
        transaction.rollback()
        connection.close()
