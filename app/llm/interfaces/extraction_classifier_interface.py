from abc import ABC, abstractmethod

from app.llm.dtos import ExtractionResult


class ExtractionClassifierInterface(ABC):
    @abstractmethod
    def extract_tier1(
        self,
        post_text: str,
        raw_message_id: int | None = None,
    ) -> ExtractionResult:
        """Presence gate + general fields only (no per-category detail calls)."""
        pass

    @abstractmethod
    def extract(
        self,
        post_text: str,
        raw_message_id: int | None = None,
    ) -> ExtractionResult:
        pass
