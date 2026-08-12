from sqlalchemy import desc, func, literal, select
from sqlalchemy.orm import Session

from app.interfaces.repositories import VillageRepositoryInterface
from app.models.news import Village


class VillageRepository(VillageRepositoryInterface):
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_active(self) -> list[Village]:
        return list(
            self.db.scalars(
                select(Village)
                .where(Village.is_active.is_(True))
                .order_by(Village.acs_code.asc())
            ).all()
        )

    def find_best_match_by_normalized_name(
        self,
        normalized_location: str,
    ) -> tuple[Village, float] | None:
        acs_similarity = func.similarity(Village.acs_name, literal(normalized_location))
        ref_similarity = func.similarity(Village.ref_name_ar, literal(normalized_location))
        best_similarity = func.greatest(acs_similarity, ref_similarity).label("score")

        row = self.db.execute(
            select(Village, best_similarity)
            .where(Village.is_active.is_(True))
            .order_by(desc(best_similarity))
            .limit(1)
        ).first()
        if row is None:
            return None

        village, score = row
        return village, float(score or 0.0)
