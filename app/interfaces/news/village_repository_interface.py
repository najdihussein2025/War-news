from abc import ABC, abstractmethod

from app.models.news import Village


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
