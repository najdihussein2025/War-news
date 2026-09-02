from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.ollama_client import JsonObject, OllamaChatClient, OllamaChatMessage
from app.llm.dtos import ExtractionCategoryKey

logger = logging.getLogger(__name__)

ALLOWED_EXTRACTION_CATEGORY_KEYS = frozenset(
    category.value for category in ExtractionCategoryKey
)
LOW_TEMPERATURE = 0.0
MUNICIPAL_INFRASTRUCTURE_TERMS = (
    "بلدية",
    "مبنى البلدية",
    "مباني البلدية",
    "مجلس بلدي",
    "مجلس البلدة",
    "موظف",
    "موظفين",
    "موظفي البلدية",
    "عامل",
    "عاملين",
    "موظف بلدي",
)
VILLAGE_LOCATION_MARKERS = (
    "بلدة",
    "مدينة",
    "قرية",
    "مزارع",
    "دوحة",
    "مشاع",
    "اطراف",
    "أطراف",
    "حرش",
    "وادي",
)
TARGETING_VERBS = (
    "استهدف",
    "استهدفت",
    "قصف",
    "غارة",
    "أغار",
    "اعتد",
)
VEHICLE_TERMS = (
    "سيارة",
    "سيارات",
    "مركبة",
    "مركبات",
    "آلية",
    "آليات",
    "دراجة",
    "دراجات",
    "موتور",
    "موتورات",
    "شاحنة",
    "شاحنات",
    "جرافة",
    "جرافات",
    "حفارة",
    "حفارات",
    "دبابة",
    "دبابات",
    "كميون",
    "بلدوزر",
)
CIVIL_DEFENSE_ORG_TERMS = (
    "الدفاع المدني",
    "دفاع مدني",
    "الصليب الأحمر",
    "الهلال الأحمر",
    "الإسعاف",
    "إسعاف",
    "مسعف",
    "سيارة إسعاف",
    "سيارات إسعاف",
    "فرق الإنقاذ",
)
PROMPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "phase2-extraction-testing"
    / "presence_gate_instruction.txt"
)
PRESENCE_GATE_PROMPT = PROMPT_PATH.read_text(encoding="utf-8")
PRESENCE_GATE_RESPONSE_SCHEMA: JsonObject = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "categories_present": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    category.value
                    for category in ExtractionCategoryKey
                ],
            },
            "uniqueItems": True,
        },
        "category_evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "category_key": {
                        "type": "string",
                        "enum": [
                            category.value
                            for category in ExtractionCategoryKey
                        ],
                    },
                    "evidence_span": {"type": "string"},
                },
                "required": ["category_key", "evidence_span"],
            },
        },
    },
    "required": ["categories_present", "category_evidence"],
}


class PresenceGateEvidence(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    category_key: ExtractionCategoryKey
    evidence_span: str


class PresenceGateResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    categories_present: list[ExtractionCategoryKey] = Field(default_factory=list)
    category_evidence: list[PresenceGateEvidence] = Field(default_factory=list)


class _RawPresenceGateEvidence(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    category_key: str
    evidence_span: str = ""


class _PresenceGateResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    categories_present: list[str] = Field(default_factory=list)
    category_evidence: list[_RawPresenceGateEvidence] = Field(default_factory=list)


class OllamaPresenceGateService:
    def __init__(self, client: OllamaChatClient) -> None:
        self.client = client

    def categories_present(
        self,
        post_text: str,
        raw_message_id: int | None = None,
    ) -> list[ExtractionCategoryKey]:
        return self.evaluate(
            post_text,
            raw_message_id=raw_message_id,
        ).categories_present

    def evaluate(
        self,
        post_text: str,
        raw_message_id: int | None = None,
    ) -> PresenceGateResult:
        content = self.client.chat(
            [
                OllamaChatMessage(role="system", content=PRESENCE_GATE_PROMPT),
                OllamaChatMessage(role="user", content=post_text),
            ],
            response_format=PRESENCE_GATE_RESPONSE_SCHEMA,
            temperature=LOW_TEMPERATURE,
        )
        return self._parse_response(
            content,
            raw_message_id=raw_message_id,
            post_text=post_text,
        )

    def parse_presence_payload(
        self,
        payload: dict,
        *,
        raw_message_id: int | None,
        post_text: str,
    ) -> PresenceGateResult:
        """Parse presence fields from a combined Tier-1 response payload."""
        presence_payload = {
            "categories_present": payload.get("categories_present", []),
            "category_evidence": payload.get("category_evidence", []),
        }
        return self._parse_response(
            json.dumps(presence_payload, ensure_ascii=False),
            raw_message_id=raw_message_id,
            post_text=post_text,
        )

    def _parse_response(
        self,
        content: str,
        raw_message_id: int | None,
        post_text: str,
    ) -> PresenceGateResult:
        try:
            payload = json.loads(content.strip())
            response = _PresenceGateResponse.model_validate(payload)
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            logger.warning(
                "Malformed presence gate response from model=%s "
                "for raw_message_id=%s: %s",
                self.client.model,
                raw_message_id,
                exc,
            )
            raise RuntimeError("Malformed presence gate response.") from exc

        validated: list[ExtractionCategoryKey] = []
        seen: set[ExtractionCategoryKey] = set()
        for raw_key in response.categories_present:
            if raw_key not in ALLOWED_EXTRACTION_CATEGORY_KEYS:
                logger.warning(
                    "Dropped invalid extraction category for raw_message_id=%s: %s",
                    raw_message_id,
                    raw_key,
                )
                continue

            category_key = ExtractionCategoryKey(raw_key)
            if category_key in seen:
                continue
            validated.append(category_key)
            seen.add(category_key)

        evidence_by_key: dict[ExtractionCategoryKey, PresenceGateEvidence] = {}
        for item in response.category_evidence:
            if item.category_key not in ALLOWED_EXTRACTION_CATEGORY_KEYS:
                logger.warning(
                    "Dropped invalid presence evidence category for raw_message_id=%s: %s",
                    raw_message_id,
                    item.category_key,
                )
                continue

            category_key = ExtractionCategoryKey(item.category_key)
            if category_key not in seen:
                logger.warning(
                    "Dropped unmatched presence evidence for raw_message_id=%s: %s",
                    raw_message_id,
                    item.category_key,
                )
                continue
            if category_key in evidence_by_key:
                continue
            evidence_span = item.evidence_span.strip()
            if self._is_context_only_evidence(
                category_key=category_key,
                evidence_span=evidence_span,
                post_text=post_text,
            ):
                logger.warning(
                    "Dropped context-only presence evidence category=%s "
                    "raw_message_id=%s: %s",
                    category_key.value,
                    raw_message_id,
                    evidence_span,
                )
                seen.discard(category_key)
                continue
            evidence_by_key[category_key] = PresenceGateEvidence(
                category_key=category_key,
                evidence_span=evidence_span,
            )

        category_evidence = [
            evidence_by_key.get(
                category_key,
                PresenceGateEvidence(category_key=category_key, evidence_span=""),
            )
            for category_key in validated
            if category_key in seen
        ]
        filtered_evidence: list[PresenceGateEvidence] = []
        filtered_categories: list[ExtractionCategoryKey] = []
        for item in category_evidence:
            if self._is_context_only_evidence(
                category_key=item.category_key,
                evidence_span=item.evidence_span,
                post_text=post_text,
            ):
                logger.warning(
                    "Dropped context-only final presence evidence category=%s "
                    "raw_message_id=%s: %s",
                    item.category_key.value,
                    raw_message_id,
                    item.evidence_span,
                )
                continue
            filtered_categories.append(item.category_key)
            filtered_evidence.append(item)

        filtered_categories, filtered_evidence = self._apply_deterministic_additions(
            post_text=post_text,
            categories=filtered_categories,
            category_evidence=filtered_evidence,
        )

        return PresenceGateResult(
            categories_present=filtered_categories,
            category_evidence=filtered_evidence,
        )

    def _apply_deterministic_additions(
        self,
        post_text: str,
        categories: list[ExtractionCategoryKey],
        category_evidence: list[PresenceGateEvidence],
    ) -> tuple[list[ExtractionCategoryKey], list[PresenceGateEvidence]]:
        seen = set(categories)
        updated_categories = list(categories)
        updated_evidence = list(category_evidence)

        if (
            ExtractionCategoryKey.emergency_civil_defense not in seen
            and self._has_civil_defense_organization_language(post_text)
        ):
            updated_categories.append(ExtractionCategoryKey.emergency_civil_defense)
            updated_evidence.append(
                PresenceGateEvidence(
                    category_key=ExtractionCategoryKey.emergency_civil_defense,
                    evidence_span=self._extract_civil_defense_evidence_span(post_text),
                )
            )

        return updated_categories, updated_evidence

    def _has_civil_defense_organization_language(self, post_text: str) -> bool:
        return any(term in post_text for term in CIVIL_DEFENSE_ORG_TERMS)

    def _extract_civil_defense_evidence_span(self, post_text: str) -> str:
        for term in CIVIL_DEFENSE_ORG_TERMS:
            index = post_text.find(term)
            if index >= 0:
                start = max(0, index - 20)
                end = min(len(post_text), index + len(term) + 40)
                return post_text[start:end].strip()
        return post_text[:80].strip()

    def _has_municipal_infrastructure_language(self, text: str) -> bool:
        return any(term in text for term in MUNICIPAL_INFRASTRUCTURE_TERMS)

    def _is_bare_village_targeting(self, evidence_span: str, post_text: str) -> bool:
        text = evidence_span.strip() or post_text
        has_location_marker = any(marker in text for marker in VILLAGE_LOCATION_MARKERS)
        has_targeting = any(verb in text for verb in TARGETING_VERBS)
        return (
            has_location_marker
            and has_targeting
            and not self._has_municipal_infrastructure_language(text)
        )

    def _has_vehicle_language(self, evidence_span: str, post_text: str) -> bool:
        text = f"{evidence_span}\n{post_text}"
        return any(term in text for term in VEHICLE_TERMS)

    def _is_context_only_evidence(
        self,
        category_key: ExtractionCategoryKey,
        evidence_span: str,
        post_text: str,
    ) -> bool:
        text = f"{evidence_span}\n{post_text}"
        proximity_terms = (
            "قرب",
            "بالقرب",
            "بجوار",
            "بجانب",
            "محيط",
            "أمام",
            "محاذاة",
        )
        negative_impact_terms = (
            "لم تسجل أضرار",
            "لم تسجّل أضرار",
            "دون تسجيل إصابات",
            "من دون تسجيل إصابات",
            "لا أضرار",
        )
        direct_impact_terms = (
            "استهدف",
            "استهدفت",
            "أصاب",
            "أصابت",
            "سقطت",
            "تضرر",
            "تضررت",
            "أضرار",
            "دمر",
            "دمرت",
            "قطع",
            "تعذر مرور",
            "أصيب",
            "أصيبت",
            "قتل",
            "قتلت",
            "استشهد",
            "جرح",
            "جرحت",
            "إخلاء",
        )

        if any(term in text for term in negative_impact_terms) and category_key in {
                ExtractionCategoryKey.hospital,
                ExtractionCategoryKey.health_center,
                ExtractionCategoryKey.religious_cultural,
                ExtractionCategoryKey.school_university,
                ExtractionCategoryKey.municipality,
                ExtractionCategoryKey.government_building,
        }:
            return True

        if category_key in {
            ExtractionCategoryKey.hospital,
            ExtractionCategoryKey.health_center,
            ExtractionCategoryKey.religious_cultural,
            ExtractionCategoryKey.school_university,
            ExtractionCategoryKey.municipality,
            ExtractionCategoryKey.government_building,
        }:
            if any(term in evidence_span for term in proximity_terms):
                return not any(term in evidence_span for term in direct_impact_terms)

        if category_key == ExtractionCategoryKey.road_bridge:
            if any(term in evidence_span for term in ("الطريق", "الجسر", "الأوتوستراد")) and not any(
                term in evidence_span
                for term in ("استهدف الطريق", "استهدفت الطريق", "قطع", "تعذر مرور")
            ):
                return True

        if category_key == ExtractionCategoryKey.lebanese_army:
            if "مواكبة" in text or "بمواكبة" in text:
                return not any(
                    term in text
                    for term in ("استهدف الجيش", "استهدفت الجيش", "أصيب عسكري", "قتل عسكري")
                )

        if category_key == ExtractionCategoryKey.emergency_civil_defense:
            if "قسم الطوارئ" in text and not any(
                term in text
                for term in ("الدفاع المدني", "الصليب الأحمر", "إسعاف", "مسعف")
            ):
                return True

        if category_key == ExtractionCategoryKey.municipality:
            if self._is_bare_village_targeting(evidence_span, post_text):
                return True
            if not self._has_municipal_infrastructure_language(
                f"{evidence_span}\n{post_text}"
            ) and any(marker in evidence_span for marker in VILLAGE_LOCATION_MARKERS):
                return True

        if category_key == ExtractionCategoryKey.vehicles:
            if not self._has_vehicle_language(evidence_span, post_text):
                return True

        if category_key == ExtractionCategoryKey.hospital:
            if "إلى المستشفى" in text or "الى المستشفى" in text:
                return not any(term in text for term in direct_impact_terms)

        return False
