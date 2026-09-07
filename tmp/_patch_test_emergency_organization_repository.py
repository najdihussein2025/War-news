from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401
from app.news.repositories.emergency_organization_repository import (
    EmergencyOrganizationRepository,
)


class _ResultStub:
    def __init__(self, rows) -> None:
        self.rows = rows

    def all(self):
        return self.rows


class _SessionStub:
    def __init__(self) -> None:
        self.statement = None

    def execute(self, statement):
        self.statement = statement
        return _ResultStub([(SimpleNamespace(id=5), 0.71)])


def test_find_similar_builds_word_similarity_sql_with_alias_unnest() -> None:
    db = _SessionStub()
    repo = EmergencyOrganizationRepository(db)  # type: ignore[arg-type]

    results = repo.find_similar("سيارة اسعاف تابعة للصليب الاحمر")

    assert len(results) == 1
    assert results[0][0].id == 5
    assert results[0][1] == 0.71
    sql = str(db.statement.compile(dialect=postgresql.dialect()))
    assert "word_similarity(" in sql
    assert "unnest(emergency_organizations.aliases)" in sql
    assert "emergency_organizations.is_active IS true" in sql


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL is required for pg_trgm integration coverage.",
)
def test_find_similar_integration_matches_seeded_generic_alias() -> None:
    from sqlalchemy import create_engine

    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        db = Session(bind=engine)
        try:
            repo = EmergencyOrganizationRepository(db)
            rows = repo.find_similar("وصلت سيارة إسعاف إلى المكان")
        finally:
            db.close()
    except OperationalError as exc:  # pragma: no cover
        pytest.skip(f"database unavailable for integration coverage: {exc}")
    finally:
        engine.dispose()

    if not rows:
        pytest.skip("emergency_organizations table is empty (seed not run).")

    top_org, top_score = rows[0]
    assert top_score > 0.0
    assert "إسعاف" in (top_org.name_ar or "") or any(
        "إسعاف" in (alias or "") for alias in (top_org.aliases or [])
    )
