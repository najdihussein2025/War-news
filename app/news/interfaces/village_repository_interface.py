from abc import ABC, abstractmethod

from app.news.models import Village


class VillageRepositoryInterface(ABC):
    @abstractmethod
    def list_active(self) -> list[Village]:
        pass

    @abstractmethod
    def find_best_match_by_normalized_name(
        self,
        normalized_location: str,
    ) -> tuple[Village, float] | None:
        pass

    @abstractmethod
    def find_similar(
        self,
        text: str,
        limit: int = 5,
    ) -> list[tuple[Village, float]]:
        pass

    def resolve_alias(self, normalized_text: str) -> tuple[Village, float] | None:
        """Exact normalized location-alias → parent village, or None.

        Default no-op so lightweight test stubs need not implement aliases.
        """
        return None
