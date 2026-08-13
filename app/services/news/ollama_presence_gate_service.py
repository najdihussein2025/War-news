from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.ollama_client import JsonObject, OllamaChatClient, OllamaChatMessage
from app.dtos.news import ExtractionCategoryKey

logger = logging.getLogger(__name__)

ALLOWED_EXTRACTION_CATEGORY_KEYS = frozenset(
    category.value for category in ExtractionCategoryKey
)
LOW_TEMPERATURE = 0.0
PROMPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "phase2-extraction-testing"
    / "presence_gate_instruction.txt"
)
PRESENCE_GATE_PROMPT = PROMPT_PATH.read_text(encoding="utf-8")
PRESENCE_GATE_RESPONSE_SCHEMA: JsonObject = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "categories_present": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    category.value
                    for category in ExtractionCategoryKey
                ],
            },
            "uniqueItems": True,
        }
    },
    "required": ["categories_present"],
}


class _PresenceGateResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    categories_present: list[str] = Field(default_factory=list)


class OllamaPresenceGateService:
    def __init__(self, client: OllamaChatClient) -> None:
        self.client = client

    def categories_present(
        self,
        post_text: str,
        raw_message_id: int | None = None,
    ) -> list[ExtractionCategoryKey]:
        content = self.client.chat(
            [
                OllamaChatMessage(role="system", content=PRESENCE_GATE_PROMPT),
                OllamaChatMessage(role="user", content=post_text),
            ],
            response_format=PRESENCE_GATE_RESPONSE_SCHEMA,
            temperature=LOW_TEMPERATURE,
        )
        return self._parse_response(content, raw_message_id=raw_message_id)

    def _parse_response(
        self,
        content: str,
        raw_message_id: int | None,
    ) -> list[ExtractionCategoryKey]:
        try:
            payload = json.loads(content.strip())
            response = _PresenceGateResponse.model_validate(payload)
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            logger.warning(
                "Malformed presence gate response from model=%s "
                "for raw_message_id=%s: %s",
                self.client.model,
                raw_message_id,
                exc,
            )
            raise RuntimeError("Malformed presence gate response.") from exc

        validated: list[ExtractionCategoryKey] = []
        seen: set[ExtractionCategoryKey] = set()
        for raw_key in response.categories_present:
            if raw_key not in ALLOWED_EXTRACTION_CATEGORY_KEYS:
                logger.warning(
                    "Dropped invalid extraction category for raw_message_id=%s: %s",
                    raw_message_id,
                    raw_key,
                )
                continue

            category_key = ExtractionCategoryKey(raw_key)
            if category_key in seen:
                continue
            validated.append(category_key)
            seen.add(category_key)

        return validated
