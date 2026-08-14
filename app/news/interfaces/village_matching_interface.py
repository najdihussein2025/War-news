from abc import ABC, abstractmethod

from app.news.models import Village


class VillageMatchingInterface(ABC):
    @abstractmethod
    def match(self, location_text: str) -> Village | None:
        pass
