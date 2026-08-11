from dataclasses import dataclass

from app.core.text_normalization import normalize_arabic_text, normalize_english_text
from app.interfaces.news import (
    ConditionRepositoryInterface,
    KeywordPrefilterInterface,
    VillageRepositoryInterface,
)
from app.models.news import Condition, Village


@dataclass(frozen=True)
class _KeywordCache:
    arabic_keywords: frozenset[str]
    english_keywords: frozenset[str]


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


class KeywordPrefilterService(KeywordPrefilterInterface):
    def __init__(
        self,
        village_repository: VillageRepositoryInterface,
        condition_repository: ConditionRepositoryInterface,
    ) -> None:
        self.village_repository = village_repository
        self.condition_repository = condition_repository
        self._cache: _KeywordCache | None = None

    def has_candidate_keywords(self, text: str) -> bool:
        cache = self._get_keyword_cache()
        normalized_arabic_text = normalize_arabic_text(text)
        normalized_english_text = normalize_english_text(text)

        return any(
            keyword in normalized_arabic_text for keyword in cache.arabic_keywords
        ) or any(
            keyword in normalized_english_text for keyword in cache.english_keywords
        )

    def clear_cache(self) -> None:
        self._cache = None

    def _get_keyword_cache(self) -> _KeywordCache:
        if self._cache is None:
            self._cache = self._load_keyword_cache(
                villages=self.village_repository.list_active(),
                conditions=self.condition_repository.list_active(),
            )
        return self._cache

    @staticmethod
    def _load_keyword_cache(
        villages: list[Village],
        conditions: list[Condition],
    ) -> _KeywordCache:
        arabic_keywords: set[str] = set()
        english_keywords: set[str] = set()

        for village in villages:
            _add_english_keyword(english_keywords, village.acs_name)
            _add_english_keyword(english_keywords, village.ref_name_en)
            _add_arabic_keyword(arabic_keywords, village.ref_name_ar)

        for condition in conditions:
            _add_english_keyword(english_keywords, condition.action_en)
            _add_arabic_keyword(arabic_keywords, condition.action_ar)

        return _KeywordCache(
            arabic_keywords=frozenset(arabic_keywords),
            english_keywords=frozenset(english_keywords),
        )
