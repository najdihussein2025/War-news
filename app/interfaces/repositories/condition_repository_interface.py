from abc import ABC, abstractmethod

from app.models.news import Condition


class ConditionRepositoryInterface(ABC):
    @abstractmethod
    def list_active(self) -> list[Condition]:
        pass

    @abstractmethod
    def find_similar(
        self,
        text: str,
        limit: int = 5,
    ) -> list[tuple[Condition, float]]:
        pass
