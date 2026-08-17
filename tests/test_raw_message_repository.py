import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401
from app.news.models import MessageStatus, RawMessage
from app.news.repositories.raw_message_repository import RawMessageRepository
from app.sources.models import Source, SourceType


def test_mark_cluster_duplicates_rolls_back_when_a_member_is_missing() -> None:
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
    try:
        marker = uuid4().hex
        source = Source(
            type=SourceType.manual,
            name=f"clustering-atomicity-{marker}",
            config={},
        )
        db.add(source)
        db.flush()

        representative = RawMessage(
            source_id=source.id,
            external_message_id=f"{marker}-representative",
            raw_payload={},
            status=MessageStatus.parsed,
        )
        member = RawMessage(
            source_id=source.id,
            external_message_id=f"{marker}-member",
            raw_payload={},
            status=MessageStatus.parsed,
        )
        db.add_all([representative, member])
        db.flush()
        representative_id = representative.id
        member_id = member.id
        missing_id = max(representative_id, member_id) + 1_000_000_000
        db.commit()

        repository = RawMessageRepository(db)
        with pytest.raises(ValueError, match="RawMessage ids not found"):
            repository.mark_cluster_duplicates(
                representative_id=representative_id,
                member_ids=[member_id, missing_id],
            )

        persisted_member = db.get(RawMessage, member_id)
        assert persisted_member is not None
        assert persisted_member.status == MessageStatus.parsed
        assert persisted_member.duplicate_of_id is None
    except (OperationalError, ProgrammingError) as exc:
        pytest.skip(f"Raw message schema is unavailable: {exc}")
    finally:
        db.close()
        transaction.rollback()
        connection.close()
