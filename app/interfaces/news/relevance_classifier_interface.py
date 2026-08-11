from abc import ABC, abstractmethod

from app.dtos.news import RelevanceClassificationResult


class RelevanceClassifierInterface(ABC):
    @abstractmethod
    def classify(self, post_text: str) -> RelevanceClassificationResult:
        pass
