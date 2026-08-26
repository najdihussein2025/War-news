from __future__ import annotations

import httpx

OLLAMA_AUTH_ERROR_MARKER = "ollama_auth_failed_401"


class OllamaAuthFailure(RuntimeError):
    def __init__(self, *, stage: str) -> None:
        self.stage = stage
        super().__init__(ollama_auth_error_message(stage))


def is_ollama_auth_failure(exc: BaseException) -> bool:
    if isinstance(exc, OllamaAuthFailure):
        return True
    if not isinstance(exc, httpx.HTTPStatusError):
        return False
    return exc.response.status_code == 401


def coerce_ollama_auth_failure(
    exc: BaseException,
    *,
    stage: str,
) -> OllamaAuthFailure | None:
    if not is_ollama_auth_failure(exc):
        return None
    if isinstance(exc, OllamaAuthFailure):
        return exc
    return OllamaAuthFailure(stage=stage)


def ollama_auth_error_message(stage: str) -> str:
    return (
        f"{OLLAMA_AUTH_ERROR_MARKER}: Ollama authentication failed during "
        f"{stage} (401 Unauthorized)"
    )
