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
from app.llm.dtos import ExtractionResult
from app.news.dtos import MatchResultStatus
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


def test_compact_sql_normalization_removes_internal_spaces() -> None:
    sql = str(
        select(normalize_arabic_sql(literal("دير ميماس"), compact=True)).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "replace" in sql


def test_compact_arabic_normalization_handles_final_ya() -> None:
    assert normalize_arabic_text("على", compact=True) == "علي"


def test_condition_query_includes_evidence_backed_aliases() -> None:
    db = _SessionStub()
    ConditionRepository(db).find_similar("تنفيذ عملية تفجير")

    sql = str(db.statement.compile(dialect=postgresql.dialect()))
    assert "CASE" in sql


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


def test_generic_strike_does_not_match_warning_or_feigned_with_real_repository() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for pg_trgm integration coverage.")

    from datetime import datetime, timezone

    from sqlalchemy import create_engine

    from app.news.repositories.village_repository import VillageRepository
    from app.news.services.matching_service import MatchingService

    def _extraction(action: str) -> ExtractionResult:
        return ExtractionResult(
            is_relevant=True,
            village=None,
            action_description=action,
            model="test",
            extracted_at=datetime.now(timezone.utc),
        )

    engine = create_engine(database_url)
    try:
        db = Session(bind=engine)
        villages = VillageRepository(db)
        conditions = ConditionRepository(db)
        service = MatchingService(villages, conditions)

        generic_strike = _extraction("غارة تستهدف بلدة المنصوري")
        warning_raid = _extraction("غارة تحذيرية من مسيرة على البيسارية")
        feigned_attacks = _extraction(
            "طيران العدو الحربي يخرق أجواء منطقة النبطية وينفذ غارات وهمية"
        )

        generic_result = service.match(generic_strike)
        warning_result = service.match(warning_raid)
        feigned_result = service.match(feigned_attacks)

        assert generic_result.matched_condition_id not in {2, 39}
        assert generic_result.condition_match_status == MatchResultStatus.unmatched
        assert warning_result.matched_condition_id == 2
        assert warning_result.condition_match_status == MatchResultStatus.matched
        assert feigned_result.matched_condition_id == 39
        assert feigned_result.condition_match_status == MatchResultStatus.matched
    except (OperationalError, ProgrammingError) as exc:
        pytest.skip(f"Condition schema or pg_trgm is unavailable: {exc}")
    finally:
        if "db" in locals():
            db.close()
