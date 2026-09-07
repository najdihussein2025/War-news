from abc import ABC, abstractmethod

from app.news.models import EmergencyOrganization


class EmergencyOrganizationRepositoryInterface(ABC):
    @abstractmethod
    def list_active(self) -> list[EmergencyOrganization]:
        pass

    @abstractmethod
    def find_similar(
        self,
        text: str,
        limit: int = 5,
    ) -> list[tuple[EmergencyOrganization, float]]:
        pass
