from abc import ABC, abstractmethod

from app.dtos.news import ClassificationResultDTO
from app.models.news import RawMessage


class RelevanceClassifierInterface(ABC):
    @abstractmethod
    async def classify_batch(
        self,
        messages: list[RawMessage],
    ) -> list[ClassificationResultDTO]:
        pass
