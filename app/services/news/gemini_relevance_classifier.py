import json
from datetime import datetime, timezone

from pydantic import BaseModel, Field, ValidationError

from app.dtos.news import RelevanceClassificationResult
from app.interfaces.news import RelevanceClassifierInterface
from app.services.news.gemini_client import GeminiRateLimitedClient

GEMINI_RELEVANCE_MODEL = "gemini-2.5-flash"


class _GeminiRelevanceResponse(BaseModel):
    relevant: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


class _GeminiBatchRelevanceResponse(_GeminiRelevanceResponse):
    index: int


class GeminiRelevanceClassifier(RelevanceClassifierInterface):
    def __init__(
        self,
        model: str = GEMINI_RELEVANCE_MODEL,
        gemini_client: GeminiRateLimitedClient | None = None,
    ) -> None:
        self.model = model
        self.gemini_client = gemini_client or GeminiRateLimitedClient()

    def classify(self, post_text: str) -> RelevanceClassificationResult:
        try:
            response_text = self.gemini_client.generate_json(
                model=self.model,
                prompt=self._build_prompt(post_text),
            )
        except Exception as exc:
            raise RuntimeError(f"Gemini relevance classification failed: {exc}") from exc

        try:
            payload = json.loads(response_text)
            parsed = _GeminiRelevanceResponse.model_validate(payload)
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            raise RuntimeError(
                f"Failed to parse Gemini relevance response: {response_text}"
            ) from exc

        return RelevanceClassificationResult(
            relevant=parsed.relevant,
            confidence=parsed.confidence,
            reasoning=parsed.reasoning,
            model=self.model,
            classified_at=datetime.now(timezone.utc),
        )

    def classify_batch(
        self,
        post_texts: list[str],
    ) -> list[RelevanceClassificationResult]:
        if not post_texts:
            return []

        try:
            response_text = self.gemini_client.generate_json(
                model=self.model,
                prompt=self._build_batch_prompt(post_texts),
            )
        except Exception as exc:
            raise RuntimeError(
                f"Gemini batch relevance classification failed: {exc}"
            ) from exc

        try:
            payload = json.loads(response_text)
            if not isinstance(payload, list):
                raise ValueError("response is not a JSON array")
            parsed = [
                _GeminiBatchRelevanceResponse.model_validate(item)
                for item in payload
            ]
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Failed to parse Gemini batch relevance response: {response_text}"
            ) from exc

        expected_indices = list(range(1, len(post_texts) + 1))
        actual_indices = [item.index for item in parsed]
        if len(parsed) != len(post_texts):
            raise RuntimeError(
                "Gemini batch relevance response count mismatch: "
                f"expected {len(post_texts)}, got {len(parsed)}"
            )
        if actual_indices != expected_indices:
            raise RuntimeError(
                "Gemini batch relevance response indices must be sequential 1..N: "
                f"expected {expected_indices}, got {actual_indices}"
            )

        classified_at = datetime.now(timezone.utc)
        return [
            RelevanceClassificationResult(
                relevant=item.relevant,
                confidence=item.confidence,
                reasoning=item.reasoning,
                model=self.model,
                classified_at=classified_at,
            )
            for item in parsed
        ]

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

    @staticmethod
    def _build_batch_prompt(post_texts: list[str]) -> str:
        numbered_posts = "\n\n".join(
            f"{index}. {post_text}"
            for index, post_text in enumerate(post_texts, start=1)
        )
        return (
            "Classify each numbered post for whether it describes a real, specific "
            "Israeli military action against Lebanon, such as an airstrike, shelling, "
            "ground incursion, drone strike, arrest, or similar military/security "
            "action. Exclude political commentary, analysis, unrelated news, "
            "non-specific claims, and events outside Lebanon. Err toward inclusion "
            "on ambiguous cases because a missed real incident is worse than an "
            "extra one filtered at extraction. Handle Arabic, English, and mixed "
            "text.\n\n"
            "Return strict JSON only: an array in the same order as the input, with "
            "exactly one object per input text. Each object must have exactly these "
            "keys: index, relevant, confidence, reasoning. The index must be the "
            "1-based input number, and confidence must be a number from 0 to 1.\n\n"
            'Example shape: [{"index": 1, "relevant": true, "confidence": 0.93, '
            '"reasoning": "specific strike in Lebanon"}]\n\n'
            f"Posts:\n{numbered_posts}"
        )
