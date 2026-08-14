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
