from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.news import Village


class VillageRepository:
    def list_active(self, db: Session) -> list[Village]:
        return list(
            db.scalars(
                select(Village)
                .where(Village.is_active.is_(True))
                .order_by(Village.acs_code.asc())
            ).all()
        )
