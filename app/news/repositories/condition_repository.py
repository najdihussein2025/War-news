from sqlalchemy import desc, func, literal, select
from sqlalchemy.orm import Session

from app.core.text_normalization import normalize_arabic_sql
from app.news.interfaces import ConditionRepositoryInterface
from app.news.models import Condition


class ConditionRepository(ConditionRepositoryInterface):
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_active(self) -> list[Condition]:
        return list(
            self.db.scalars(
                select(Condition)
                .where(Condition.is_active.is_(True))
                .order_by(Condition.id.asc())
            ).all()
        )

    def find_similar(
        self,
        text: str,
        limit: int = 5,
    ) -> list[tuple[Condition, float]]:
        normalized_action = normalize_arabic_sql(Condition.action_ar)
        score = func.similarity(normalized_action, literal(text)).label("score")
        rows = self.db.execute(
            select(Condition, score)
            .where(Condition.is_active.is_(True))
            .order_by(desc(score), Condition.id.asc())
            .limit(limit)
        ).all()
        return [(condition, float(value or 0.0)) for condition, value in rows]
