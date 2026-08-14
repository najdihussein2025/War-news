from __future__ import annotations

import asyncio

from app.core.ollama_client import OllamaChatClient
from app.llm.dtos import ClassificationResultDTO
from app.news.models import (
    MessageStatus,
    RawMessage,
)
from app.llm.services.local_llm_relevance_classifier import (
    LOCAL_LLM_RELEVANCE_BACKEND,
    REASON_VALIDATION_FALLBACK,
    RELEVANCE_CLASSIFICATION_PROMPT,
    LocalLLMRelevanceClassifier,
    is_valid_reason_text,
)


class OllamaRelevanceClassifierService(LocalLLMRelevanceClassifier):
    """Backward-compatible name for the local LLM relevance classifier."""

    def __init__(self, client: OllamaChatClient) -> None:
        super().__init__(client=client, backend=LOCAL_LLM_RELEVANCE_BACKEND)

    def classify(
        self,
        post_text: str,
        raw_message_id: int | None = None,
    ) -> ClassificationResultDTO:
        message = RawMessage(
            id=raw_message_id or 0,
            source_id=0,
            raw_text=post_text,
            raw_payload={},
            status=MessageStatus.pending,
        )
        return asyncio.run(self.classify_batch([message]))[0]


__all__ = [
    "LOCAL_LLM_RELEVANCE_BACKEND",
    "REASON_VALIDATION_FALLBACK",
    "RELEVANCE_CLASSIFICATION_PROMPT",
    "OllamaRelevanceClassifierService",
    "is_valid_reason_text",
]
