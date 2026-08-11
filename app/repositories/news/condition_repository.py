from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.news import Condition


class ConditionRepository:
    def list_active(self, db: Session) -> list[Condition]:
        return list(
            db.scalars(
                select(Condition)
                .where(Condition.is_active.is_(True))
                .order_by(Condition.id.asc())
            ).all()
        )
