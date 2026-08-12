from abc import ABC, abstractmethod


class KeywordPrefilterInterface(ABC):
    @abstractmethod
    def has_candidate_keywords(self, text: str) -> bool:
        pass
