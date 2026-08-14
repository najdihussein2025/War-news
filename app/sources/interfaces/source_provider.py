from abc import ABC, abstractmethod


class SourceProvider(ABC):
    @abstractmethod
    def fetch_batch(
        self,
        cursor: str | None,
        limit: int = 500,
    ) -> tuple[list[dict], str | None, bool]:
        """Fetch one page of normalized raw source items."""
