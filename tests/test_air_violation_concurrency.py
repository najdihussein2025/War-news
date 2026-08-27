from datetime import date
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.news.dtos import AirViolationUpdateDTO
from app.accounts.models import User
from app.news.models import AirViolation, Condition
from app.news.repositories import AirViolationRepository
from app.news.services import AirViolationConflictError, AirViolationService
from app.sources.models import Source, SourceType


def _payload(version: int = 1) -> AirViolationUpdateDTO:
    return AirViolationUpdateDTO(
        condition_id=35,
        caza_en="Sour",
        event_date=date(2026, 8, 27),
        khabar="Updated news",
        version=version,
    )


class _StaleRepository:
    def update(self, air_violation_id: int, payload: AirViolationUpdateDTO, user_id):
        raise StaleDataError("stale update")

    def delete(self, air_violation_id: int, version: int, user_id):
        raise StaleDataError("stale delete")


def test_service_rejects_stale_air_violation_update() -> None:
    service = AirViolationService(_StaleRepository())  # type: ignore[arg-type]

    with pytest.raises(AirViolationConflictError, match="updated by another administrator"):
        service.update(42, _payload(), uuid4())


def test_service_rejects_stale_air_violation_delete() -> None:
    service = AirViolationService(_StaleRepository())  # type: ignore[arg-type]

    with pytest.raises(AirViolationConflictError, match="updated by another administrator"):
        service.delete(42, version=1, user_id=uuid4())


def test_repository_atomically_rejects_a_stale_version() -> None:
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
        user = db.query(User).first()
        if user is None:
            pytest.skip("An administrator account is required for edit-lock coverage.")
        source = Source(
            type=SourceType.manual,
            name="Concurrency Test",
            external_id=f"air-violation-concurrency-{marker}",
            config={},
        )
        db.add(source)
        db.flush()
        violation = AirViolation(
            condition_id=condition.id,
            source_id=source.id,
            caza_en="Sour",
            event_date=date(2026, 8, 27),
            khabar="Original",
        )
        db.add(violation)
        db.flush()
        violation_id = violation.id

        repository = AirViolationRepository(db)
        locked = repository.acquire_edit_lock(violation_id, user.id)
        assert locked is not None
        with pytest.raises(StaleDataError, match="being edited"):
            repository.acquire_edit_lock(violation_id, uuid4())
        updated = repository.update(violation_id, _payload(version=1), user.id)

        assert updated is not None
        assert updated.version == 2
        with pytest.raises(StaleDataError):
            repository.update(violation_id, _payload(version=1), user.id)
        with pytest.raises(StaleDataError):
            repository.delete(violation_id, version=1, user_id=user.id)
    finally:
        db.close()
        transaction.rollback()
        connection.close()
