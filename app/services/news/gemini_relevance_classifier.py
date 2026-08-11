import json
from datetime import datetime, timezone

from google import genai
from pydantic import BaseModel, Field, ValidationError

from app.core.config import settings
from app.dtos.news import RelevanceClassificationResult
from app.interfaces.news import RelevanceClassifierInterface

GEMINI_RELEVANCE_MODEL = "gemini-2.5-flash"


class _GeminiRelevanceResponse(BaseModel):
    relevant: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


class GeminiRelevanceClassifier(RelevanceClassifierInterface):
    def __init__(self, model: str = GEMINI_RELEVANCE_MODEL) -> None:
        self.model = model

    def classify(self, post_text: str) -> RelevanceClassificationResult:
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured.")

        client = genai.Client(api_key=settings.gemini_api_key)
        try:
            response = client.models.generate_content(
                model=self.model,
                contents=self._build_prompt(post_text),
                config={"response_mime_type": "application/json"},
            )
        except Exception as exc:
            raise RuntimeError(f"Gemini relevance classification failed: {exc}") from exc

        if not response.text:
            raise RuntimeError("Gemini returned an empty relevance response.")

        try:
            payload = json.loads(response.text)
            parsed = _GeminiRelevanceResponse.model_validate(payload)
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            raise RuntimeError(
                f"Failed to parse Gemini relevance response: {response.text}"
            ) from exc

        return RelevanceClassificationResult(
            relevant=parsed.relevant,
            confidence=parsed.confidence,
            reasoning=parsed.reasoning,
            model=self.model,
            classified_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _build_prompt(post_text: str) -> str:
        return (
            "Classify whether this post describes a real, specific Israeli military "
            "action against Lebanon, such as an airstrike, shelling, ground incursion, "
            "drone strike, arrest, or similar military/security action. Exclude "
            "political commentary, analysis, unrelated news, non-specific claims, and "
            "events outside Lebanon. Err toward inclusion on ambiguous cases because "
            "a missed real incident is worse than an extra one filtered at extraction. "
            "Handle Arabic, English, and mixed text.\n\n"
            "Return strict JSON only with exactly these keys: relevant, confidence, "
            "reasoning. The confidence must be a number from 0 to 1.\n\n"
            f"Post text:\n{post_text}"
        )
