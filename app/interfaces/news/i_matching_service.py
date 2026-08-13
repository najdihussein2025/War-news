from abc import ABC, abstractmethod

from app.dtos.news import ExtractionResult, MatchResultDTO


class MatchingServiceInterface(ABC):
    @abstractmethod
    def match(self, extraction_result: ExtractionResult) -> MatchResultDTO:
        pass
