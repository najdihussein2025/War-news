from abc import ABC, abstractmethod

from app.llm.dtos import ExtractionResult


class ExtractionClassifierInterface(ABC):
    @abstractmethod
    def extract(
        self,
        post_text: str,
        raw_message_id: int | None = None,
    ) -> ExtractionResult:
        pass
