from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Mapping, TypeAlias, cast

import httpx

JsonValue: TypeAlias = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)
JsonObject: TypeAlias = dict[str, JsonValue]


@dataclass(frozen=True)
class OllamaChatMessage:
    role: str
    content: str


class OllamaChatClient:
    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        model: str,
        timeout_seconds: int,
        max_request_retries: int = 0,
        retry_backoff_seconds: float = 0.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            headers=headers,
            transport=transport,
        )
        self._async_client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            headers=headers,
            transport=transport,
        )
        self._model = model
        self._max_request_retries = max(0, max_request_retries)
        self._retry_backoff_seconds = max(0.0, retry_backoff_seconds)

    @property
    def model(self) -> str:
        return self._model

    def chat(
        self,
        messages: list[OllamaChatMessage],
        response_format: str | JsonObject = "json",
        temperature: float | None = None,
    ) -> str:
        request_payload: JsonObject = {
            "model": self._model,
            "stream": False,
            "format": response_format,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
        }
        if temperature is not None:
            request_payload["options"] = {"temperature": temperature}

        response = self._send_with_retries("api/chat", request_payload)
        response.raise_for_status()
        return self._content_from_payload(response.json())

    async def chat_async(
        self,
        messages: list[OllamaChatMessage],
        response_format: str | JsonObject = "json",
        temperature: float | None = None,
    ) -> str:
        request_payload: JsonObject = {
            "model": self._model,
            "stream": False,
            "format": response_format,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
        }
        if temperature is not None:
            request_payload["options"] = {"temperature": temperature}

        response = await self._send_with_retries_async("api/chat", request_payload)
        response.raise_for_status()
        return self._content_from_payload(response.json())

    def _send_with_retries(
        self,
        path: str,
        request_payload: JsonObject,
    ) -> httpx.Response:
        last_exc: BaseException | None = None
        for attempt in range(self._max_request_retries + 1):
            try:
                response = self._client.post(path, json=request_payload)
                if response.status_code in {502, 503, 504}:
                    response.raise_for_status()
                return response
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                if not self._is_retryable_exception(exc) or attempt >= self._max_request_retries:
                    raise
                last_exc = exc
                self._sleep_before_retry(attempt)
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("Ollama request failed without a captured exception.")

    async def _send_with_retries_async(
        self,
        path: str,
        request_payload: JsonObject,
    ) -> httpx.Response:
        last_exc: BaseException | None = None
        for attempt in range(self._max_request_retries + 1):
            try:
                response = await self._async_client.post(path, json=request_payload)
                if response.status_code in {502, 503, 504}:
                    response.raise_for_status()
                return response
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                if not self._is_retryable_exception(exc) or attempt >= self._max_request_retries:
                    raise
                last_exc = exc
                await self._sleep_before_retry_async(attempt)
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("Ollama request failed without a captured exception.")

    def _is_retryable_exception(self, exc: BaseException) -> bool:
        if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in {502, 503, 504}
        return False

    def _sleep_before_retry(self, attempt: int) -> None:
        if self._retry_backoff_seconds <= 0:
            return
        time.sleep(self._retry_backoff_seconds * (attempt + 1))

    async def _sleep_before_retry_async(self, attempt: int) -> None:
        if self._retry_backoff_seconds <= 0:
            return
        await asyncio.sleep(self._retry_backoff_seconds * (attempt + 1))

    @staticmethod
    def _content_from_payload(payload: JsonObject) -> str:
        if not isinstance(payload, Mapping):
            raise RuntimeError("Ollama response payload is not an object.")

        message = payload.get("message")
        if not isinstance(message, Mapping):
            raise RuntimeError("Ollama response does not include a message object.")

        content = message.get("content")
        if not isinstance(content, str):
            raise RuntimeError("Ollama response message content is not a string.")

        return cast(str, content)
