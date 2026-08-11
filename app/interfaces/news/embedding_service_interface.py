from abc import ABC, abstractmethod


class EmbeddingServiceInterface(ABC):
    @abstractmethod
    def generate(self, text: str) -> list[float]:
        pass
