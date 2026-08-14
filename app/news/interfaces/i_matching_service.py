from abc import ABC, abstractmethod

from app.llm.dtos import ExtractionResult
from app.news.dtos import MatchResultDTO


class MatchingServiceInterface(ABC):
    @abstractmethod
    def match(self, extraction_result: ExtractionResult) -> MatchResultDTO:
        pass
