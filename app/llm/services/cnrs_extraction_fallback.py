from __future__ import annotations

from typing import Any

from app.core.database import SessionLocal
from app.core.llm_knowledge.loader import terms_by_category
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
from app.llm.services.cnrs_relevance_classifier import verdict_from_cnrs_classification
from app.llm.dtos import ClassificationVerdict
from app.news.models import RawMessage
from app.news.services.matching.conflict_attribution import (
    has_conflict_attribution_text,
)


SUBTYPE_ACTIONS = {
    "airstrike": "Bombs",
    "artillery": "Artillery Shelling",
    "fire_incident": "Burning Properties",
}

_MOTORCYCLE_TEXT_MARKERS = tuple(
    term
    for term in terms_by_category("terminology/role_terms.yaml", "vehicle_term")
    if term in {"دراج", "موتور"}
) or ("دراج", "موتور")
_TANK_MARKERS = tuple(
    term
    for term in terms_by_category("terminology/role_terms.yaml", "vehicle_term")
    if term in {"دبابة", "دبابات"}
) or ("دبابة",)


def has_conflict_attribution(
    classification: dict[str, Any] | None,
    post_text: str,
) -> bool:
    """Return True if text or metadata explicitly attributes the event to war/conflict action."""
    if classification:
        if classification.get("mentions_israeli_actor") is True:
            return True
    return has_conflict_attribution_text(post_text)


def trusted_cnrs_action(
    classification: dict[str, Any] | None,
    post_text: str,
) -> str | None:
    """Map a supported CNRS subtype to its trusted incident condition."""
    if not classification or classification.get("include") is not True:
        return None
    if verdict_from_cnrs_classification(classification) != ClassificationVerdict.relevant:
        return None
    subtype = str(classification.get("event_subtype") or "").strip().lower()
    if subtype == "direct_attack":
        return (
            "Tank Fire"
            if any(marker in post_text for marker in _TANK_MARKERS)
            else "Bombs"
        )
    if subtype == "fire_incident":
        # Fires require explicit war/conflict causal attribution to avoid civilian/traffic false positives.
        if not has_conflict_attribution(classification, post_text):
            return None
    return SUBTYPE_ACTIONS.get(subtype)


def _has_text_grounded_action(result: ExtractionResult) -> bool:
    if (result.action_description or "").strip():
        return True
    return any(
        (sub_event.action_text or "").strip()
        or (sub_event.evidence_span or "").strip()
        for sub_event in result.sub_events
    )


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
        subtype = str(classification.get("event_subtype") or "").strip().lower() or None
        action = trusted_cnrs_action(classification, post_text)
        villages, village_roles = cls._merge_location(result, location)
        has_text_grounded_action = _has_text_grounded_action(result)

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
                "action_description": (
                    result.action_description
                    if has_text_grounded_action
                    else action or result.action_description
                ),
                "action_source": (
                    "llm_text"
                    if has_text_grounded_action
                    else "cnrs_subtype_fallback"
                    if action is not None
                    else result.action_source
                ),
                "source_event_subtype": subtype,
                "source_action_hint": action,
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
