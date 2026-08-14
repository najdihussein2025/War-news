from abc import ABC, abstractmethod

from app.llm.dtos import ClassificationResultDTO
from app.news.models import RawMessage


class RelevanceClassifierInterface(ABC):
    @abstractmethod
    async def classify_batch(
        self,
        messages: list[RawMessage],
    ) -> list[ClassificationResultDTO]:
        pass
