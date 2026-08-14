from abc import ABC, abstractmethod

from app.news.models import Condition


class ConditionResolutionInterface(ABC):
    @abstractmethod
    def resolve(
        self,
        action_en: str,
        conditions: list[Condition],
    ) -> Condition | None:
        pass
