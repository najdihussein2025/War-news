from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.text_normalization import normalize_arabic_text, normalize_english_text
from app.repositories.news import ConditionRepository, VillageRepository


@dataclass(frozen=True)
class _KeywordCache:
    arabic_keywords: frozenset[str]
    english_keywords: frozenset[str]


_keyword_cache: _KeywordCache | None = None


def _add_arabic_keyword(keywords: set[str], value: str | None) -> None:
    if not value:
        return
    normalized = normalize_arabic_text(value)
    if normalized:
        keywords.add(normalized)


def _add_english_keyword(keywords: set[str], value: str | None) -> None:
    if not value:
        return
    normalized = normalize_english_text(value)
    if normalized:
        keywords.add(normalized)


def _load_keyword_cache(db: Session) -> _KeywordCache:
    arabic_keywords: set[str] = set()
    english_keywords: set[str] = set()

    for village in VillageRepository().list_active(db):
        _add_english_keyword(english_keywords, village.acs_name)
        _add_english_keyword(english_keywords, village.ref_name_en)
        _add_arabic_keyword(arabic_keywords, village.ref_name_ar)

    for condition in ConditionRepository().list_active(db):
        _add_english_keyword(english_keywords, condition.action_en)
        _add_arabic_keyword(arabic_keywords, condition.action_ar)

    return _KeywordCache(
        arabic_keywords=frozenset(arabic_keywords),
        english_keywords=frozenset(english_keywords),
    )


def _get_keyword_cache(db: Session | None = None) -> _KeywordCache:
    global _keyword_cache
    if _keyword_cache is not None:
        return _keyword_cache

    if db is not None:
        _keyword_cache = _load_keyword_cache(db)
        return _keyword_cache

    local_db = SessionLocal()
    try:
        _keyword_cache = _load_keyword_cache(local_db)
        return _keyword_cache
    finally:
        local_db.close()


def clear_keyword_cache() -> None:
    global _keyword_cache
    _keyword_cache = None


def has_candidate_keywords(text: str, db: Session | None = None) -> bool:
    cache = _get_keyword_cache(db)
    normalized_arabic_text = normalize_arabic_text(text)
    normalized_english_text = normalize_english_text(text)

    return any(
        keyword in normalized_arabic_text for keyword in cache.arabic_keywords
    ) or any(
        keyword in normalized_english_text for keyword in cache.english_keywords
    )
