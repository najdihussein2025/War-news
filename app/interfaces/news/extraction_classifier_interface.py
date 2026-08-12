from abc import ABC, abstractmethod

from app.dtos.news import ExtractionResult


class ExtractionClassifierInterface(ABC):
    @abstractmethod
    def extract_candidates(
        self,
        post_text: str,
        conditions: list[tuple[str, str]],
    ) -> ExtractionResult:
        pass
