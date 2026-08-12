from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.ollama_client import OllamaChatClient, OllamaChatMessage
from app.dtos.news import RelevanceClassificationResult, RelevanceConfidence
from app.interfaces.services import RelevanceClassifierInterface

logger = logging.getLogger(__name__)

RELEVANCE_CLASSIFICATION_PROMPT = """You classify one Arabic news text before incident extraction.

Return strict JSON only with exactly these fields:
{"is_relevant": true/false, "confidence": "high"/"medium"/"low", "reason": "<short explanation>"}

Strict output rules:
- Return one valid JSON object only.
- Do not write any text before or after the JSON.
- Do not use Markdown or code fences.
- Do not write comments inside or outside JSON.
- Do not add extra fields.
- Do not guess beyond what the text explicitly states.
- Read only the provided text; do not use outside knowledge.

Inclusion criteria:
Set "is_relevant" to true only when the text describes a physical event that occurred in Lebanon and involves at least one of:
- airstrike
- shelling
- ground incursion
- IED or explosion
- armed clash
- drone strike
- casualties from military or security action
- infrastructure damage from conflict

Exclusion criteria:
Set "is_relevant" to false when the text describes:
- events in other countries, even if military-themed, including Gaza or Syria
- natural disasters
- political statements, diplomacy, threats, analysis, or commentary with no physical incident
- general or unrelated news, including shipping, economics, entertainment, or politics unrelated to Lebanon security

Confidence rules:
- Use "high" only when the text clearly satisfies the inclusion or exclusion criteria.
- Use "medium" when the likely verdict is clear but the text leaves one important detail ambiguous.
- Use "low" when the text is too vague to classify confidently.

The reason must be short and based only on the text."""


class _RelevanceLLMResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    is_relevant: bool
    confidence: RelevanceConfidence
    reason: str = Field(min_length=1, max_length=300)


class OllamaRelevanceClassifierService(RelevanceClassifierInterface):
    def __init__(self, client: OllamaChatClient) -> None:
        self.client = client

    def classify(self, post_text: str) -> RelevanceClassificationResult:
        content = self.client.chat(
            [
                OllamaChatMessage(
                    role="system",
                    content=RELEVANCE_CLASSIFICATION_PROMPT,
                ),
                OllamaChatMessage(role="user", content=post_text),
            ]
        )
        return self._parse_response(content)

    def classify_batch(
        self,
        post_texts: list[str],
    ) -> list[RelevanceClassificationResult]:
        return [self.classify(post_text) for post_text in post_texts]

    def _parse_response(self, content: str) -> RelevanceClassificationResult:
        try:
            raw_payload = json.loads(content.strip())
            response = _RelevanceLLMResponse.model_validate(raw_payload)
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            logger.warning(
                "Malformed relevance classification response from model=%s: %s",
                self.client.model,
                exc,
            )
            return RelevanceClassificationResult(
                is_relevant=None,
                confidence=None,
                reason="Malformed relevance classification response.",
                model=self.client.model,
                classified_at=datetime.now(timezone.utc),
                parse_error=str(exc),
            )

        return RelevanceClassificationResult(
            is_relevant=response.is_relevant,
            confidence=response.confidence,
            reason=response.reason,
            model=self.client.model,
            classified_at=datetime.now(timezone.utc),
        )
