import os
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
from app.news.dtos import AirViolationListParams
from app.news.models import AirViolation, Condition, MessageStatus, RawMessage
from app.news.repositories.air_violation_repository import AirViolationRepository
from app.sources.models import Source, SourceType


def test_air_violation_uses_original_message_source_name() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for repository integration coverage.")

    engine = create_engine(database_url)
    try:
        connection = engine.connect()
    except OperationalError as exc:
        pytest.skip(f"Database is unavailable: {exc}")

    transaction = connection.begin()
    db = Session(bind=connection, join_transaction_mode="create_savepoint")
    marker = uuid4().hex
    try:
        condition = db.get(Condition, 35)
        if condition is None:
            pytest.skip("Air-violation condition 35 is unavailable.")

        source = Source(
            type=SourceType.api,
            name="CNRS Webhook",
            external_id=f"source-test-{marker}",
            config={},
        )
        db.add(source)
        db.flush()
        message = RawMessage(
            source_id=source.id,
            external_message_id=f"message-test-{marker}",
            source_platform="telegram",
            source_name="original-channel",
            origin_account="original-account",
            raw_payload={},
            status=MessageStatus.parsed,
        )
        db.add(message)
        db.flush()
        db.add(
            AirViolation(
                raw_message_id=message.id,
                condition_id=condition.id,
                source_id=source.id,
                caza_en=marker,
                event_date=date(2026, 8, 18),
                khabar="Source mapping test",
            )
        )
        db.flush()

        result = AirViolationRepository(db).list_all(
            AirViolationListParams(caza_en=marker)
        )

        assert result.total == 1
        assert result.items[0].source_name == "original-account"
    except (OperationalError, ProgrammingError) as exc:
        pytest.skip(f"Air-violation schema is unavailable: {exc}")
    finally:
        db.close()
        transaction.rollback()
        connection.close()
