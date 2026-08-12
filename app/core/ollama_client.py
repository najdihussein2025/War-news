from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, cast

import httpx


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
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    def chat(self, messages: list[OllamaChatMessage]) -> str:
        response = self._client.post(
            "/api/chat",
            json={
                "model": self._model,
                "stream": False,
                "format": "json",
                "messages": [
                    {"role": message.role, "content": message.content}
                    for message in messages
                ],
            },
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise RuntimeError("Ollama response payload is not an object.")

        message = payload.get("message")
        if not isinstance(message, Mapping):
            raise RuntimeError("Ollama response does not include a message object.")

        content = message.get("content")
        if not isinstance(content, str):
            raise RuntimeError("Ollama response message content is not a string.")

        return cast(str, content)
