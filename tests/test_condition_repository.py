import os
from types import SimpleNamespace

import pytest
from sqlalchemy import func, literal, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401
from app.core.text_normalization import (
    normalize_arabic_sql,
    normalize_arabic_text,
)
from app.news.models import Condition
from app.news.repositories.condition_repository import ConditionRepository


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
        return _ResultStub([(SimpleNamespace(id=35), 0.466667)])


def test_condition_query_uses_word_similarity() -> None:
    db = _SessionStub()
    repository = ConditionRepository(db)  # type: ignore[arg-type]

    result = repository.find_similar(
        normalize_arabic_text(
            "الطيران الحربي الإسرائيلي أغار مستهدفًا بلدة المنصوري بغارتين"
        )
    )

    sql = str(
        db.statement.compile(  # type: ignore[union-attr]
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "word_similarity" in sql
    assert result[0][0].id == 35
    assert result[0][1] == pytest.approx(0.466667)


def test_real_verbose_airstrike_prefers_warplane_over_artillery() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for pg_trgm integration coverage.")

    from sqlalchemy import create_engine

    engine = create_engine(database_url)
    try:
        db = Session(bind=engine)
        text = normalize_arabic_text(
            "الطيران الحربي الإسرائيلي أغار مستهدفًا بلدة المنصوري بغارتين"
        )
        candidates = ConditionRepository(db).find_similar(text)
        artillery_score = db.scalar(
            select(
                func.word_similarity(
                    normalize_arabic_sql(Condition.action_ar),
                    literal(text),
                )
            ).where(Condition.action_ar == "قصف مدفعي")
        )

        assert candidates[0][0].action_ar == "طيران حربي"
        assert candidates[0][1] > 0.35
        assert float(artillery_score or 0.0) < 0.35
    except (OperationalError, ProgrammingError) as exc:
        pytest.skip(f"Condition schema or pg_trgm is unavailable: {exc}")
    finally:
        if "db" in locals():
            db.close()
