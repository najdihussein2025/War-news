import threading
import time
from typing import Any

from google import genai

from app.core.config import settings

GEMINI_MIN_SECONDS_BETWEEN_CALLS = 13.0


class GeminiRateLimitedClient:
    _lock = threading.Lock()
    _last_call_at = 0.0

    def __init__(self, min_spacing_seconds: float = GEMINI_MIN_SECONDS_BETWEEN_CALLS) -> None:
        self.min_spacing_seconds = min_spacing_seconds

    def generate_json(self, model: str, prompt: str) -> str:
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured.")

        client = genai.Client(api_key=settings.gemini_api_key)
        try:
            response = self._generate_with_retry(client=client, model=model, prompt=prompt)
        except Exception as exc:
            raise RuntimeError(f"Gemini API request failed: {exc}") from exc

        if not response.text:
            raise RuntimeError("Gemini returned an empty response.")
        return response.text

    def _generate_with_retry(self, client: Any, model: str, prompt: str) -> Any:
        try:
            return self._generate_once(client=client, model=model, prompt=prompt)
        except Exception as exc:
            if not self._is_rate_limit_error(exc):
                raise
            time.sleep(self.min_spacing_seconds)
            return self._generate_once(client=client, model=model, prompt=prompt)

    def _generate_once(self, client: Any, model: str, prompt: str) -> Any:
        with self._lock:
            elapsed = time.monotonic() - self._last_call_at
            if elapsed < self.min_spacing_seconds:
                time.sleep(self.min_spacing_seconds - elapsed)

            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config={"response_mime_type": "application/json"},
            )
            self.__class__._last_call_at = time.monotonic()
            return response

    @staticmethod
    def _is_rate_limit_error(exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
        if status_code == 429:
            return True
        return "429" in str(exc)
