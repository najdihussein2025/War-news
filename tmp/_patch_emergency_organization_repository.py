from sqlalchemy import desc, func, literal, select
from sqlalchemy.orm import Session

from app.core.text_normalization import normalize_arabic_sql
from app.news.interfaces import EmergencyOrganizationRepositoryInterface
from app.news.models import EmergencyOrganization


class EmergencyOrganizationRepository(EmergencyOrganizationRepositoryInterface):
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_active(self) -> list[EmergencyOrganization]:
        return list(
            self.db.scalars(
                select(EmergencyOrganization)
                .where(EmergencyOrganization.is_active.is_(True))
                .order_by(EmergencyOrganization.id.asc())
            ).all()
        )

    def find_similar(
        self,
        text: str,
        limit: int = 5,
    ) -> list[tuple[EmergencyOrganization, float]]:
        # word_similarity() for verbose Arabic phrase matching (project
        # convention), plus a compact-key score so spacing variants still
        # match — mirrors village_repository.find_similar(). Aliases are scored
        # via unnest(...).column_valued() (table_valued("value") breaks on
        # Postgres text[] unnest, which is not a record-returning function).
        normalized_text = normalize_arabic_sql(literal(text))
        compact_text = normalize_arabic_sql(literal(text), compact=True)
        normalized_name_en = func.lower(func.trim(EmergencyOrganization.name_en))

        alias_col = func.unnest(EmergencyOrganization.aliases).column_valued(
            "alias_text"
        )
        alias_score = (
            select(
                func.coalesce(
                    func.max(
                        func.greatest(
                            func.word_similarity(
                                normalize_arabic_sql(alias_col),
                                normalized_text,
                            ),
                            func.word_similarity(
                                normalize_arabic_sql(alias_col, compact=True),
                                compact_text,
                            ),
                        )
                    ),
                    0.0,
                )
            )
            .correlate(EmergencyOrganization)
            .scalar_subquery()
        )

        score = func.greatest(
            func.word_similarity(
                normalize_arabic_sql(EmergencyOrganization.name_ar), normalized_text
            ),
            func.word_similarity(
                normalize_arabic_sql(EmergencyOrganization.name_ar, compact=True),
                compact_text,
            ),
            func.word_similarity(normalized_name_en, func.lower(normalized_text)),
            alias_score,
        ).label("score")

        rows = self.db.execute(
            select(EmergencyOrganization, score)
            .where(EmergencyOrganization.is_active.is_(True))
            .order_by(desc(score), EmergencyOrganization.id.asc())
            .limit(limit)
        ).all()
        return [(org, float(value or 0.0)) for org, value in rows]
