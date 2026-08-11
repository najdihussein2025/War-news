import json
from datetime import datetime, timezone

from pydantic import TypeAdapter, ValidationError

from app.dtos.news import ExtractedCandidate, ExtractionResult
from app.interfaces.news import ExtractionClassifierInterface
from app.services.news.gemini_client import GeminiRateLimitedClient

GEMINI_EXTRACTION_MODEL = "gemini-2.5-flash"


class GeminiExtractionClassifier(ExtractionClassifierInterface):
    def __init__(
        self,
        model: str = GEMINI_EXTRACTION_MODEL,
        gemini_client: GeminiRateLimitedClient | None = None,
    ) -> None:
        self.model = model
        self.gemini_client = gemini_client or GeminiRateLimitedClient()

    def extract_candidates(
        self,
        post_text: str,
        conditions: list[tuple[str, str]],
    ) -> ExtractionResult:
        try:
            response_text = self.gemini_client.generate_json(
                model=self.model,
                prompt=self._build_prompt(post_text=post_text, conditions=conditions),
            )
        except Exception as exc:
            raise RuntimeError(f"Gemini incident extraction failed: {exc}") from exc

        try:
            payload = json.loads(response_text)
            candidates = TypeAdapter(list[ExtractedCandidate]).validate_python(payload)
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            raise RuntimeError(
                f"Failed to parse Gemini extraction response: {response_text}"
            ) from exc

        return ExtractionResult(
            candidates=candidates,
            model=self.model,
            extracted_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _build_prompt(post_text: str, conditions: list[tuple[str, str]]) -> str:
        condition_lines = "\n".join(
            f"- action_en: {action_en} | action_ar: {action_ar}"
            for action_en, action_ar in conditions
        )
        return (
            "Extract incident candidates from this relevant news/social post. "
            "Identify EVERY distinct concrete action or incident described. A post can "
            "describe zero, one, or multiple distinct actions, so do not artificially "
            "limit the result to one candidate. For example, a post describing both a "
            "ground incursion in one town and a separate shooting incident in another "
            "town should produce two candidates.\n\n"
            "You must use this closed conditions vocabulary. The action_en value in "
            "every response object MUST be an exact action_en value from this list; "
            "never invent or paraphrase it:\n"
            f"{condition_lines}\n\n"
            "For location_text, extract only the raw village/town/location text as it "
            "appears in the post. Do not normalize, translate, or match it. A later "
            "database step handles village matching.\n\n"
            "For casualty fields, fill only values explicitly stated in the post. Use "
            "null for anything that is not explicitly stated; never infer demographic "
            "breakdowns from totals.\n\n"
            "Return strict JSON only: an array of objects with exactly these keys: "
            "location_text, action_en, deaths, injuries, male_d, male_i, female_d, "
            "female_i, children_d, children_i, confidence, reasoning. Confidence must "
            "be a number from 0 to 1. Return [] if the post describes no concrete "
            "incident despite passing the relevance filter.\n\n"
            f"Post text:\n{post_text}"
        )
