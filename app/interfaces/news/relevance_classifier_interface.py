from abc import ABC, abstractmethod

from app.dtos.news import RelevanceClassificationResult


class RelevanceClassifierInterface(ABC):
    @abstractmethod
    def classify(self, post_text: str) -> RelevanceClassificationResult:
        pass

    @abstractmethod
    def classify_batch(
        self,
        post_texts: list[str],
    ) -> list[RelevanceClassificationResult]:
        pass
