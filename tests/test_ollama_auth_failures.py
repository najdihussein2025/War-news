from __future__ import annotations

import httpx

from app.llm.services.ollama_auth_failures import (
    OLLAMA_AUTH_ERROR_MARKER,
    OllamaAuthFailure,
    coerce_ollama_auth_failure,
    is_ollama_auth_failure,
)


def _http_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://ollama.test/api/chat")
    response = httpx.Response(status_code=status_code, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


def test_recognizes_401_as_ollama_auth_failure() -> None:
    exc = _http_status_error(401)

    assert is_ollama_auth_failure(exc) is True
    coerced = coerce_ollama_auth_failure(exc, stage="tier1_extraction")
    assert isinstance(coerced, OllamaAuthFailure)
    assert OLLAMA_AUTH_ERROR_MARKER in str(coerced)


def test_ignores_non_401_http_errors() -> None:
    exc = _http_status_error(500)

    assert is_ollama_auth_failure(exc) is False
    assert coerce_ollama_auth_failure(exc, stage="tier1_extraction") is None
