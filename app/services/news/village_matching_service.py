from sqlalchemy import desc, func, literal, select
from sqlalchemy.orm import Session

from app.core.text_normalization import normalize_arabic_text
from app.models.news import Village

# Initial pg_trgm cutoff; tune after reviewing real extraction audit results.
VILLAGE_MATCH_THRESHOLD = 0.35


def match_village(location_text: str, db: Session) -> Village | None:
    normalized_location = normalize_arabic_text(location_text)
    if not normalized_location:
        return None

    acs_similarity = func.similarity(Village.acs_name, literal(normalized_location))
    ref_similarity = func.similarity(Village.ref_name_ar, literal(normalized_location))
    best_similarity = func.greatest(acs_similarity, ref_similarity).label("score")

    row = db.execute(
        select(Village, best_similarity)
        .where(Village.is_active.is_(True))
        .order_by(desc(best_similarity))
        .limit(1)
    ).first()
    if row is None:
        return None

    village, score = row
    if score is None or score < VILLAGE_MATCH_THRESHOLD:
        return None
    return village
