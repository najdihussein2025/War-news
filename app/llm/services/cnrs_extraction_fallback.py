from __future__ import annotations

from typing import Any

from app.core.database import SessionLocal
from app.core.text_normalization import normalize_arabic_text
from app.llm.dtos import (
    ExtractionCasualties,
    ExtractionCategory,
    ExtractionCategoryKey,
    ExtractionResult,
    ExtractionVehicleDetails,
    VillageRole,
    VillageRoleEntry,
)
from app.llm.interfaces import ExtractionClassifierInterface
from app.news.models import RawMessage


SUBTYPE_ACTIONS = {
    "airstrike": "Bombs",
    "artillery": "Artillery Shelling",
    "fire_incident": "Burning Properties",
}

_MOTORCYCLE_TEXT_MARKERS = ("دراج", "موتور")


def trusted_cnrs_action(
    classification: dict[str, Any] | None,
    post_text: str,
) -> str | None:
    """Map a supported CNRS subtype to its trusted incident condition."""
    if not classification or classification.get("include") is not True:
        return None
    subtype = str(classification.get("event_subtype") or "").strip().lower()
    if subtype == "direct_attack":
        return "Tank Fire" if "دبابة" in post_text else "Bombs"
    return SUBTYPE_ACTIONS.get(subtype)


class CnrsExtractionFallback(ExtractionClassifierInterface):
    """Overlay trusted CNRS fields on complete LLM extraction."""

    def __init__(self, fallback: ExtractionClassifierInterface) -> None:
        self.fallback = fallback

    def extract_tier1(self, post_text: str, raw_message_id: int | None = None) -> ExtractionResult:
        classification = self._classification(raw_message_id)
        if classification is None:
            return self.fallback.extract_tier1(post_text, raw_message_id)
        # CNRS messages receive full category extraction before the fast path so
        # trusted routing never comes at the cost of missing incident details.
        result = self.fallback.extract(post_text, raw_message_id)
        return self._apply_cnrs_overrides(result, classification, post_text)

    def extract(self, post_text: str, raw_message_id: int | None = None) -> ExtractionResult:
        classification = self._classification(raw_message_id)
        result = self.fallback.extract(post_text, raw_message_id)
        if classification is None:
            return result
        return self._apply_cnrs_overrides(result, classification, post_text)

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
    def _classification(raw_message_id: int | None) -> dict[str, Any] | None:
        if raw_message_id is None:
            return None
        with SessionLocal() as db:
            message = db.get(RawMessage, raw_message_id)
            classification = message.cnrs_classification if message is not None else None
        if not classification or classification.get("include") is not True:
            return None
        return dict(classification)

    @classmethod
    def _apply_cnrs_overrides(
        cls,
        result: ExtractionResult,
        classification: dict[str, Any],
        post_text: str,
    ) -> ExtractionResult:
        location = str(classification.get("location") or "").strip()
        action = trusted_cnrs_action(classification, post_text)
        villages, village_roles = cls._merge_location(result, location)

        categories = dict(result.categories)
        presence_keys = list(result.presence_category_keys)
        has_motorcycle = any(
            marker in post_text
            for marker in _MOTORCYCLE_TEXT_MARKERS
        )
        if has_motorcycle:
            category_key = ExtractionCategoryKey.vehicles
            category = categories.get(category_key, ExtractionCategory())
            vehicles = category.vehicles or ExtractionVehicleDetails()
            categories[category_key] = category.model_copy(
                update={
                    "vehicles": vehicles.model_copy(update={"moto": True}),
                }
            )
            if category_key not in presence_keys:
                presence_keys.append(category_key)

        return result.model_copy(
            update={
                "is_relevant": (
                    True if location and action is not None else result.is_relevant
                ),
                "village": villages,
                "village_roles": village_roles,
                "action_description": action or result.action_description,
                "categories": categories,
                "presence_category_keys": presence_keys,
            }
        )

    @staticmethod
    def _merge_location(
        result: ExtractionResult,
        location: str,
    ) -> tuple[list[str] | None, list[VillageRoleEntry]]:
        if not location:
            return result.village, list(result.village_roles)

        roles = list(result.village_roles)
        target_indexes = [
            index
            for index, entry in enumerate(roles)
            if entry.role == VillageRole.target
        ]
        if len(target_indexes) > 1:
            return result.village, roles

        if len(target_indexes) == 1:
            index = target_indexes[0]
            target = roles[index]
            update: dict[str, Any] = {"village": location}
            if normalize_arabic_text(target.village) != normalize_arabic_text(location):
                update.update(
                    deaths=None,
                    injuries=None,
                    evidence_span=None,
                )
            roles[index] = target.model_copy(update=update)
            return [entry.village for entry in roles], roles

        if roles:
            roles.append(VillageRoleEntry(village=location, role=VillageRole.target))
            return [entry.village for entry in roles], roles

        if len(result.village or []) > 1:
            return result.village, roles
        return [location], [VillageRoleEntry(village=location, role=VillageRole.target)]
