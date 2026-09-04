from __future__ import annotations

from datetime import datetime, timezone

from app.core.database import SessionLocal
from app.llm.dtos import (
    ExtractionCasualties,
    ExtractionCategory,
    ExtractionCategoryKey,
    ExtractionResult,
)
from app.llm.interfaces import ExtractionClassifierInterface
from app.news.models import RawMessage


SUBTYPE_ACTIONS = {
    "airstrike": "Bombs",
    "artillery": "Artillery Shelling",
    "fire_incident": "Burning Properties",
}


class CnrsExtractionFallback(ExtractionClassifierInterface):
    """Use trusted CNRS structured fields before requiring an external LLM."""

    def __init__(self, fallback: ExtractionClassifierInterface) -> None:
        self.fallback = fallback

    def extract_tier1(self, post_text: str, raw_message_id: int | None = None) -> ExtractionResult:
        structured = self._structured_result(raw_message_id)
        return structured or self.fallback.extract_tier1(post_text, raw_message_id)

    def extract(self, post_text: str, raw_message_id: int | None = None) -> ExtractionResult:
        structured = self._structured_result(raw_message_id)
        return structured or self.fallback.extract(post_text, raw_message_id)

    def extract_tier2_details(
        self,
        *,
        post_text: str,
        presence_category_keys: list[ExtractionCategoryKey],
        root_casualties: ExtractionCasualties,
        raw_message_id: int | None = None,
    ) -> dict[ExtractionCategoryKey, ExtractionCategory]:
        """Tier 2 is always delegated to the full extraction classifier."""
        method = getattr(self.fallback, "extract_tier2_details")
        return method(
            post_text=post_text,
            presence_category_keys=presence_category_keys,
            root_casualties=root_casualties,
            raw_message_id=raw_message_id,
        )

    @staticmethod
    def _structured_result(raw_message_id: int | None) -> ExtractionResult | None:
        if raw_message_id is None:
            return None
        with SessionLocal() as db:
            message = db.get(RawMessage, raw_message_id)
            classification = message.cnrs_classification if message is not None else None
        if not classification or classification.get("include") is not True:
            return None
        location = str(classification.get("location") or "").strip()
        subtype = str(classification.get("event_subtype") or "").strip().lower()
        action = SUBTYPE_ACTIONS.get(subtype)
        if subtype == "direct_attack":
            action = "Tank Fire" if "دبابة" in (message.raw_text or "") else "Bombs"
        if not location:
            return None
        if not action:
            # CNRS can include relevant domains (for example weather or a
            # casualty-only update) that have no canonical incident condition.
            # Treat them as non-materializable instead of blocking current news
            # on Ollama merely to reach the same conclusion.
            return ExtractionResult(
                is_relevant=False,
                model="cnrs_provided",
                extracted_at=datetime.now(timezone.utc),
                extraction_tier=1,
            )
        return ExtractionResult(
            is_relevant=True,
            village=[location],
            action_description=action,
            model="cnrs_provided",
            extracted_at=datetime.now(timezone.utc),
            extraction_tier=1,
        )
