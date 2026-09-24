from abc import ABC, abstractmethod

from typing import Any

from app.llm.dtos import ExtractionResult
from app.news.dtos import MatchResultDTO


class MatchingServiceInterface(ABC):
    @abstractmethod
    def match(
        self,
        extraction_result: ExtractionResult,
        *,
        cnrs_classification: dict[str, Any] | None = None,
    ) -> MatchResultDTO:
        pass
