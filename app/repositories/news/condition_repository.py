from sqlalchemy import select
from sqlalchemy.orm import Session

from app.interfaces.news import ConditionRepositoryInterface
from app.models.news import Condition


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
