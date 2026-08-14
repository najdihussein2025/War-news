from __future__ import annotations

import asyncio
import json
import logging
import string
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.ollama_client import OllamaChatClient, OllamaChatMessage
from app.dtos.news import ClassificationResultDTO, ClassificationVerdict
from app.interfaces.news import RelevanceClassifierInterface
from app.models.news import RawMessage

logger = logging.getLogger(__name__)

LOCAL_LLM_RELEVANCE_BACKEND = "local_llm_gpt_oss_20b"
LOW_TEMPERATURE = 0.0
REASON_VALIDATION_FALLBACK = "Reason unavailable (response validation failed)"

RELEVANCE_CLASSIFICATION_PROMPT = """You classify Arabic news posts before incident extraction.

Return strict JSON only with exactly this shape:
{"results":[{"raw_message_id":123,"verdict":"relevant|not_relevant|uncertain","confidence":0.0,"reasoning":"<short explanation>"}]}

Strict output rules:
- Return one valid JSON object only.
- Include exactly one result for every supplied raw_message_id.
- Do not write any text before or after the JSON.
- Do not use Markdown or code fences.
- Do not add extra fields.
- Do not guess beyond what the text explicitly states.
- Read only the provided text; do not use outside knowledge.
- The reasoning field must be short and written in Arabic or English only. Never use Chinese or any other language.
- Use confidence as a number from 0.0 to 1.0.

Inclusion criteria:
Use verdict "relevant" only when the text describes a physical event that occurred in Lebanon and involves at least one of:
- airstrike
- shelling
- ground incursion
- IED or explosion
- armed clash
- drone strike
- casualties from military or security action
- infrastructure damage from conflict
- airspace violations with no strike or casualties: warplane overflight, surveillance aircraft or drone reconnaissance flight, or helicopter hovering over Lebanese territory

Exclusion criteria:
Use verdict "not_relevant" when the text describes:
- events in other countries, even if military-themed, including Gaza or Syria
- natural disasters
- political statements, diplomacy, threats, analysis, or commentary with no physical incident
- general or unrelated news, including shipping, economics, entertainment, or politics unrelated to Lebanon security

Use verdict "uncertain" when the text is too vague or ambiguous to classify safely."""


class _RelevanceLLMItem(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    raw_message_id: int
    verdict: ClassificationVerdict
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    reasoning: str | None = Field(default=None, max_length=300)


class _RelevanceLLMBatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    results: list[dict[str, Any]]


def is_valid_reason_text(reason: str) -> bool:
    if not reason.strip():
        return False

    for character in reason:
        if "\u0600" <= character <= "\u06ff":
            continue
        if character.isascii() and (
            character.isalnum()
            or character.isspace()
            or character in string.punctuation
        ):
            continue
        return False

    for token in reason.split():
        has_arabic = any("\u0600" <= character <= "\u06ff" for character in token)
        has_latin = any(character.isascii() and character.isalpha() for character in token)
        if has_arabic and has_latin:
            return False

    return True


class LocalLLMRelevanceClassifier(RelevanceClassifierInterface):
    def __init__(
        self,
        client: OllamaChatClient,
        backend: str = LOCAL_LLM_RELEVANCE_BACKEND,
        max_retries: int = 3,
        retry_backoff_seconds: float = 1.0,
    ) -> None:
        self.client = client
        self.backend = backend
        self.max_retries = max(1, max_retries)
        self.retry_backoff_seconds = retry_backoff_seconds

    async def classify_batch(
        self,
        messages: list[RawMessage],
    ) -> list[ClassificationResultDTO]:
        if not messages:
            return []

        content = await self._chat_with_retries(messages)
        return self._parse_batch_response(content, messages)

    async def _chat_with_retries(self, messages: list[RawMessage]) -> str:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return await self.client.chat_async(
                    [
                        OllamaChatMessage(
                            role="system",
                            content=RELEVANCE_CLASSIFICATION_PROMPT,
                        ),
                        OllamaChatMessage(
                            role="user",
                            content=self._format_batch(messages),
                        ),
                    ],
                    temperature=LOW_TEMPERATURE,
                )
            except (
                httpx.ConnectError,
                httpx.ConnectTimeout,
                httpx.ReadTimeout,
                httpx.RemoteProtocolError,
                httpx.NetworkError,
            ) as exc:
                last_error = exc
                if attempt == self.max_retries:
                    break
                await asyncio.sleep(self.retry_backoff_seconds * (2 ** (attempt - 1)))

        if last_error is None:
            raise RuntimeError("Local LLM relevance classifier failed without an error.")
        raise last_error

    @staticmethod
    def _format_batch(messages: list[RawMessage]) -> str:
        return json.dumps(
            [
                {
                    "raw_message_id": message.id,
                    "text": message.raw_text or "",
                }
                for message in messages
            ],
            ensure_ascii=False,
        )

    def _parse_batch_response(
        self,
        content: str,
        messages: list[RawMessage],
    ) -> list[ClassificationResultDTO]:
        try:
            raw_payload = json.loads(content.strip())
            response = _RelevanceLLMBatchResponse.model_validate(raw_payload)
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            logger.warning(
                "Malformed local relevance classification response from model=%s: %s",
                self.client.model,
                exc,
            )
            return [
                self._uncertain_result(
                    message.id,
                    reasoning="Malformed relevance classification response.",
                    raw_response={"content": content, "parse_error": str(exc)},
                )
                for message in messages
            ]

        by_id = self._parse_items(response.results)
        return [
            self._result_for_message(
                message_id=message.id,
                item=by_id.get(message.id),
                raw_payload=raw_payload,
            )
            for message in messages
        ]

    def _parse_items(
        self,
        raw_items: list[dict[str, Any]],
    ) -> dict[int, _RelevanceLLMItem | ClassificationResultDTO]:
        parsed_items: dict[int, _RelevanceLLMItem | ClassificationResultDTO] = {}
        for raw_item in raw_items:
            try:
                item = _RelevanceLLMItem.model_validate(raw_item)
                parsed_items[item.raw_message_id] = item
            except ValidationError as exc:
                message_id = self._raw_message_id_from_item(raw_item)
                if message_id is None:
                    logger.warning(
                        "Skipping relevance result with invalid raw_message_id: %s",
                        exc,
                    )
                    continue
                parsed_items[message_id] = self._uncertain_result(
                    message_id,
                    reasoning="Malformed relevance classification result.",
                    raw_response={
                        "item": raw_item,
                        "parse_error": str(exc),
                    },
                )
        return parsed_items

    @staticmethod
    def _raw_message_id_from_item(raw_item: dict[str, Any]) -> int | None:
        raw_message_id = raw_item.get("raw_message_id")
        if isinstance(raw_message_id, int) and not isinstance(raw_message_id, bool):
            return raw_message_id
        if isinstance(raw_message_id, str) and raw_message_id.isdigit():
            return int(raw_message_id)
        return None

    def _result_for_message(
        self,
        message_id: int,
        item: _RelevanceLLMItem | ClassificationResultDTO | None,
        raw_payload: dict[str, Any],
    ) -> ClassificationResultDTO:
        if item is None:
            return self._uncertain_result(
                message_id,
                reasoning="Model response omitted this message.",
                raw_response=raw_payload,
            )

        if isinstance(item, ClassificationResultDTO):
            return item

        reasoning = item.reasoning
        if reasoning and not is_valid_reason_text(reasoning):
            logger.warning(
                "Invalid relevance reasoning text from model=%s for raw_message_id=%s",
                self.client.model,
                message_id,
            )
            reasoning = REASON_VALIDATION_FALLBACK

        return ClassificationResultDTO(
            raw_message_id=message_id,
            verdict=item.verdict,
            confidence=item.confidence,
            reasoning=reasoning,
            backend=self.backend,
            raw_response=item.model_dump(mode="json"),
        )

    def _uncertain_result(
        self,
        message_id: int,
        reasoning: str,
        raw_response: dict[str, Any] | None = None,
    ) -> ClassificationResultDTO:
        return ClassificationResultDTO(
            raw_message_id=message_id,
            verdict=ClassificationVerdict.uncertain,
            confidence=None,
            reasoning=reasoning,
            backend=self.backend,
            raw_response=raw_response,
        )
