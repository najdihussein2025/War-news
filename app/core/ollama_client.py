from __future__ import annotations

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

        response = self._client.post("api/chat", json=request_payload)
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

        response = await self._async_client.post("api/chat", json=request_payload)
        response.raise_for_status()
        return self._content_from_payload(response.json())

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
