from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.config import settings
from app.core.ollama_client import JsonObject, OllamaChatClient, OllamaChatMessage
from app.core.text_normalization import normalize_arabic_text
from app.core.llm_knowledge.loader import terms_by_category
from app.core.llm_knowledge.prompt_assembly import build_stage_system_prompt
from app.llm.dtos import (
    CasualtyCountEvidence,
    CasualtyScope,
    CasualtyTransition,
    ExtractionCasualties,
    ExtractionCategory,
    ExtractionCategoryKey,
    ExtractionResult,
    ExtractionSubEvent,
    VillageRole,
    VillageRoleEntry,
)
from app.llm.interfaces import ExtractionClassifierInterface
from app.llm.services.ollama_category_detail_service import OllamaCategoryDetailService
from app.llm.services.ollama_auth_failures import coerce_ollama_auth_failure
from app.llm.services.transient_llm_errors import Tier2ExtractionFailedError
from app.llm.services.ollama_presence_gate_service import (
    LOW_TEMPERATURE,
    PRESENCE_GATE_RESPONSE_SCHEMA,
    OllamaPresenceGateService,
)
from app.llm.services.ollama_relevance_classifier_service import is_valid_reason_text
from app.news.services.incident_details.casualty_count_backstop import (
    apply_casualty_count_backstop,
)
from app.news.services.incident_details.casualty_scope_backstop import (
    validate_casualty_scope,
)

logger = logging.getLogger(__name__)

_DASH_ROUTE_RE = re.compile(
    r"طريق(?:\s+عام)?\s+"
    r"(?P<left>[\u0600-\u06ff][\u0600-\u06ff\s]{1,60}?)"
    r"\s*[-–—]\s*"
    r"(?P<right>[\u0600-\u06ff][\u0600-\u06ff\s]{1,60}?)"
    r"(?=$|[\n،؛.!؟])"
)
_BETWEEN_ROUTE_RE = re.compile(
    r"(?:طريق|مسار)\s+بين\s+"
    r"(?P<left>[\u0600-\u06ff][\u0600-\u06ff\s]{1,60}?)"
    r"\s+و\s*"
    r"(?P<right>[\u0600-\u06ff][\u0600-\u06ff\s]{1,60}?)"
    r"(?=$|[\n،؛.!؟])"
)
MULTI_VILLAGE_NO_SUBEVENTS_REVIEW_REASON = "multi_village_no_subevents"
_ACTION_FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("sweeping", ("تمشيط", "مشط", "مشطت", "sweep", "sweeping")),
    (
        "illumination_incendiary",
        (
            "قنابل مضيئة",
            "قنابل حارقة",
            "مضيئة وحارقة",
            "انارة",
            "اناره",
            "incendiary",
            "illumination",
            "flare",
            "flares",
        ),
    ),
    ("shelling", ("قصف", "قذائف", "مدفعي", "shell", "shelling")),
    ("airstrike", ("غارة", "اغارة", "استهدفت", "استهداف", "airstrike", "raid", "strike")),
    ("fire", ("حريق", "احراق", "أحرق", "حرق", "fire", "burn")),
    ("drone", ("مسيرة", "مسيّرة", "درون", "drone")),
    ("gunfire", ("اطلاق نار", "رشقات", "رصاص", "gunfire", "shooting")),
    ("movement", ("تحرك", "آليات", "اليات", "توغل", "دورية", "movement", "incursion")),
)
_DASH_QUALIFIER_RE = re.compile(
    r"(?P<prefix>بلدة|مزرعة|خراج)\s+"
    r"(?P<left>[\u0600-\u06ff][\u0600-\u06ff\s]{1,60}?)"
    r"\s*[-–—]\s*"
    r"(?P<right>[\u0600-\u06ff][\u0600-\u06ff\s]{1,80}?)"
    r"(?=$|[\n،؛.!؟])"
)
_BALDA_VILLAGE_RE = re.compile(
    r"(?:^|[^\u0600-\u06ff])"
    r"(?:بلدة|بلدات)\s+"
    r"(?P<village>[\u0600-\u06ff][\u0600-\u06ff\s]{0,40}?)"
    r"(?=\s*(?:[،؛.!؟\n]|$)|(?:\s+(?:أسفر|أدى|مما|في\s+قضاء)))"
)
# Shared-toll bulletin lists: «بلدات حولا، مارون الراس، … ويارون»
_BALDAT_LIST_RE = re.compile(
    r"بلدات\s+"
    r"(?P<body>[\u0600-\u06ff][\u0600-\u06ff\s،,]{2,200}?)"
    r"(?=\s*(?:،\s*)?(?:ما\s+)?(?:أسفر|أدى|مما)|[\n.!؟]|$)"
)
_SECONDARY_STRIKE_RE = re.compile(
    r"كما\s+طال(?:ت)?\s+(?:القصف|الغارة|الاستهداف)\s+"
    r"(?:حرج|خراج|أطراف|محيط)?\s*"
    r"بلدة\s+"
    r"(?P<village>[؀-ۿ][؀-ۿ\s]{1,40}?)"
    r"(?=\s+(?:في\s+)?قضاء|[\n،؛.!؟]|$)"
)
# Accuracy-study / bulletin connectors: «كما غارة أخرى في بلدة X»
_SECONDARY_EVENT_CONNECTOR_RE = re.compile(
    r"(?:كما|أيضا|بالإضافة(?:\s+إلى)?|من\s+جهة\s+أخرى|وفي\s+سياق\s+متصل)\s+"
    r"(?:غارة|قصف|استهداف|قصفًا|غارات)?\s*"
    r"(?:أخرى\s+)?"
    r"(?:في\s+|على\s+)?"
    r"بلدة\s+"
    r"(?P<village>[\u0600-\u06ff][\u0600-\u06ff\s]{1,40}?)"
    r"(?=\s*(?:[،؛.!؟\n]|$)|(?:\s+(?:أدى|أسفر|مما|في\s+قضاء)))"
)
_ROUTE_AREA_PREFIXES = terms_by_category(
    "terminology/role_terms.yaml",
    "route_area_prefix",
) or ("مرج ",)

ALLOWED_EXTRACTION_CATEGORY_KEYS = frozenset(
    category.value for category in ExtractionCategoryKey
)

# Deprecated module-level aliases kept for scripts/docs that still name these
# constants. Runtime Tier-1 calls use build_stage_system_prompt() so matched
# terminology and situational rules can vary per message.
GENERAL_EXTRACTION_PROMPT = (
    Path(__file__).resolve().parents[2]
    / "core"
    / "llm_knowledge"
    / "rules"
    / "tier1_general_prompt.md"
).read_text(encoding="utf-8")

GENERAL_EXTRACTION_RESPONSE_SCHEMA: JsonObject = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "is_relevant": {"type": "boolean"},
        "village": {"type": ["array", "null"], "items": {"type": "string"}},
        "village_roles": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "village": {"type": "string"},
                    "role": {
                        "type": "string",
                        "enum": ["origin", "target"],
                    },
                    "deaths": {"type": ["integer", "null"], "minimum": 0},
                    "injuries": {"type": ["integer", "null"], "minimum": 0},
                    "evidence_span": {"type": ["string", "null"]},
                    "qualifier_text": {"type": ["string", "null"]},
                },
                "required": [
                    "village",
                    "role",
                    "deaths",
                    "injuries",
                    "evidence_span",
                    "qualifier_text",
                ],
            },
        },
        "action_description": {"type": ["string", "null"]},
        "sub_events": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "locations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "village": {"type": "string"},
                                "role": {
                                    "type": "string",
                                    "enum": ["origin", "target"],
                                },
                                "deaths": {"type": ["integer", "null"], "minimum": 0},
                                "injuries": {"type": ["integer", "null"], "minimum": 0},
                                "evidence_span": {"type": ["string", "null"]},
                                "qualifier_text": {"type": ["string", "null"]},
                            },
                            "required": [
                                "village",
                                "role",
                                "deaths",
                                "injuries",
                                "evidence_span",
                                "qualifier_text",
                            ],
                        },
                    },
                    "action_text": {"type": ["string", "null"]},
                    "casualties": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "total_deaths": {"type": ["integer", "null"]},
                            "total_injuries": {"type": ["integer", "null"]},
                            "deaths": {"type": ["integer", "null"]},
                            "injuries": {"type": ["integer", "null"]},
                            "male_deaths": {"type": ["integer", "null"]},
                            "male_injuries": {"type": ["integer", "null"]},
                            "female_deaths": {"type": ["integer", "null"]},
                            "female_injuries": {"type": ["integer", "null"]},
                            "children_deaths": {"type": ["integer", "null"]},
                            "children_injuries": {"type": ["integer", "null"]},
                        },
                    },
                    "evidence_span": {"type": ["string", "null"]},
                    "casualty_evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "field": {
                                    "type": "string",
                                    "enum": [
                                        "total_deaths",
                                        "total_injuries",
                                        "deaths",
                                        "injuries",
                                        "male_deaths",
                                        "male_injuries",
                                        "female_deaths",
                                        "female_injuries",
                                        "children_deaths",
                                        "children_injuries",
                                    ],
                                },
                                "evidence_span": {"type": "string"},
                            },
                            "required": ["field", "evidence_span"],
                        },
                    },
                },
                "required": [
                    "locations",
                    "action_text",
                    "casualties",
                    "evidence_span",
                    "casualty_evidence",
                ],
            },
        },
        "casualties": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "total_deaths": {"type": ["integer", "null"]},
                "total_injuries": {"type": ["integer", "null"]},
                "deaths": {"type": ["integer", "null"]},
                "injuries": {"type": ["integer", "null"]},
                "male_deaths": {"type": ["integer", "null"]},
                "male_injuries": {"type": ["integer", "null"]},
                "female_deaths": {"type": ["integer", "null"]},
                "female_injuries": {"type": ["integer", "null"]},
                "children_deaths": {"type": ["integer", "null"]},
                "children_injuries": {"type": ["integer", "null"]},
            },
        },
        "casualty_transitions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "from_status": {
                        "type": "string",
                        "enum": ["injured", "deceased"],
                    },
                    "to_status": {
                        "type": "string",
                        "enum": ["injured", "deceased"],
                    },
                    "count": {"type": "integer", "minimum": 1},
                },
                "required": ["from_status", "to_status", "count"],
            },
        },
        "casualty_evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "field": {
                        "type": "string",
                        "enum": [
                            "total_deaths",
                            "total_injuries",
                            "deaths",
                            "injuries",
                            "male_deaths",
                            "male_injuries",
                            "female_deaths",
                            "female_injuries",
                            "children_deaths",
                            "children_injuries",
                        ],
                    },
                    "evidence_span": {"type": "string"},
                },
                "required": ["field", "evidence_span"],
            },
        },
        "casualty_scope": {
            "type": "string",
            "enum": [
                "per_village_exact",
                "bulletin_aggregate",
                "unspecified",
            ],
        },
        "casualty_scope_evidence": {"type": ["string", "null"]},
    },
    "required": [
        "is_relevant",
        "village",
        "village_roles",
        "action_description",
        "sub_events",
        "casualties",
        "casualty_transitions",
        "casualty_evidence",
        "casualty_scope",
        "casualty_scope_evidence",
    ],
}

COMBINED_TIER1_PROMPT = (
    Path(__file__).resolve().parents[2]
    / "core"
    / "llm_knowledge"
    / "rules"
    / "combined_tier1_prompt.md"
).read_text(encoding="utf-8")

COMBINED_TIER1_RESPONSE_SCHEMA: JsonObject = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "categories_present": PRESENCE_GATE_RESPONSE_SCHEMA["properties"][
            "categories_present"
        ],  # type: ignore[index]
        "category_evidence": PRESENCE_GATE_RESPONSE_SCHEMA["properties"][
            "category_evidence"
        ],  # type: ignore[index]
        "is_relevant": {"type": "boolean"},
        "village": {"type": ["array", "null"], "items": {"type": "string"}},
        "village_roles": GENERAL_EXTRACTION_RESPONSE_SCHEMA["properties"][
            "village_roles"
        ],  # type: ignore[index]
        "action_description": {"type": ["string", "null"]},
        "sub_events": GENERAL_EXTRACTION_RESPONSE_SCHEMA["properties"]["sub_events"],  # type: ignore[index]
        "casualties": GENERAL_EXTRACTION_RESPONSE_SCHEMA["properties"]["casualties"],  # type: ignore[index]
        "casualty_transitions": GENERAL_EXTRACTION_RESPONSE_SCHEMA["properties"][
            "casualty_transitions"
        ],  # type: ignore[index]
        "casualty_evidence": GENERAL_EXTRACTION_RESPONSE_SCHEMA["properties"][
            "casualty_evidence"
        ],  # type: ignore[index]
        "casualty_scope": GENERAL_EXTRACTION_RESPONSE_SCHEMA["properties"][
            "casualty_scope"
        ],  # type: ignore[index]
        "casualty_scope_evidence": GENERAL_EXTRACTION_RESPONSE_SCHEMA["properties"][
            "casualty_scope_evidence"
        ],  # type: ignore[index]
    },
    "required": [
        "categories_present",
        "category_evidence",
        "is_relevant",
        "village",
        "village_roles",
        "action_description",
        "sub_events",
        "casualties",
        "casualty_transitions",
        "casualty_evidence",
        "casualty_scope",
        "casualty_scope_evidence",
    ],
}


class _RawExtractionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    is_relevant: bool = True
    # Accept both old single-string responses and new array responses.
    village: list[str] | str | None = None
    village_roles: list[VillageRoleEntry] = Field(default_factory=list)
    action_description: str | None = None
    sub_events: list[ExtractionSubEvent] = Field(default_factory=list)
    casualties: ExtractionCasualties = Field(default_factory=ExtractionCasualties)
    casualty_transitions: list[CasualtyTransition] = Field(default_factory=list)
    casualty_evidence: list[CasualtyCountEvidence] = Field(default_factory=list)
    casualty_scope: CasualtyScope = CasualtyScope.unspecified
    casualty_scope_evidence: str | None = None

    @field_validator(
        "village_roles",
        "sub_events",
        "casualty_transitions",
        "casualty_evidence",
        mode="before",
    )
    @classmethod
    def _empty_list_for_none(cls, value: object) -> object:
        return [] if value is None else value


class OllamaExtractionService(ExtractionClassifierInterface):
    def __init__(
        self,
        client: OllamaChatClient,
        presence_gate: OllamaPresenceGateService | None = None,
        category_detail: OllamaCategoryDetailService | None = None,
        casualty_scope_aliases: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self.client = client
        self.presence_gate = presence_gate or OllamaPresenceGateService(client)
        self.category_detail = category_detail or OllamaCategoryDetailService(client)
        self.casualty_scope_aliases = casualty_scope_aliases or {}

    def extract_tier1(
        self,
        post_text: str,
        raw_message_id: int | None = None,
    ) -> ExtractionResult:
        if settings.tier1_use_combined_presence_extraction:
            return self._extract_tier1_combined(
                post_text,
                raw_message_id=raw_message_id,
            )

        categories_present = self.presence_gate.categories_present(
            post_text,
            raw_message_id=raw_message_id,
        )
        general_response = self._extract_general_fields(
            post_text,
            raw_message_id=raw_message_id,
        )
        return self._build_tier1_result(
            post_text=post_text,
            categories_present=categories_present,
            general_response=general_response,
            raw_message_id=raw_message_id,
        )

    def _extract_tier1_combined(
        self,
        post_text: str,
        raw_message_id: int | None = None,
    ) -> ExtractionResult:
        content = self.client.chat(
            [
                OllamaChatMessage(
                    role="system",
                    content=build_stage_system_prompt("combined_tier1", post_text),
                ),
                OllamaChatMessage(role="user", content=post_text),
            ],
            response_format=COMBINED_TIER1_RESPONSE_SCHEMA,
            temperature=LOW_TEMPERATURE,
        )
        try:
            payload = json.loads(content.strip())
        except json.JSONDecodeError as exc:
            logger.warning(
                "Malformed combined Tier1 response from model=%s "
                "for raw_message_id=%s: %s",
                self.client.model,
                raw_message_id,
                exc,
            )
            raise RuntimeError("Malformed combined Tier1 extraction response.") from exc

        presence_result = self.presence_gate.parse_presence_payload(
            payload,
            raw_message_id=raw_message_id,
            post_text=post_text,
        )
        general_payload = {
            key: payload.get(key)
            for key in (
                "is_relevant",
                "village",
                "village_roles",
                "action_description",
                "sub_events",
                "casualties",
                "casualty_transitions",
                "casualty_evidence",
                "casualty_scope",
                "casualty_scope_evidence",
            )
        }
        general_response = self._parse_general_response(
            json.dumps(general_payload, ensure_ascii=False),
            raw_message_id=raw_message_id,
        )
        return self._build_tier1_result(
            post_text=post_text,
            categories_present=presence_result.categories_present,
            general_response=general_response,
            raw_message_id=raw_message_id,
        )

    def _build_tier1_result(
        self,
        *,
        post_text: str,
        categories_present: list[ExtractionCategoryKey],
        general_response: _RawExtractionResponse,
        raw_message_id: int | None,
    ) -> ExtractionResult:
        casualties, casualty_evidence = apply_casualty_count_backstop(
            post_text,
            general_response.casualties,
            list(general_response.casualty_evidence),
            raw_message_id=raw_message_id,
        )
        categories: dict[ExtractionCategoryKey, ExtractionCategory] = {}
        self._inject_casualty_demographics_from_root(
            categories,
            casualties,
        )
        village_roles = self._validated_village_roles(
            general_response.village_roles,
            post_text=post_text,
            raw_message_id=raw_message_id,
        )
        villages = self._validated_village_list(
            general_response.village,
            raw_message_id=raw_message_id,
        )
        villages, village_roles = self._apply_dash_compound_location_rules(
            post_text,
            villages,
            village_roles,
        )
        (
            villages,
            village_roles,
            location_alternatives,
            location_ambiguity_evidence,
        ) = self._collapse_fuzzy_area_locations(
            post_text,
            villages,
            village_roles,
        )
        sub_events = self._validated_sub_events(
            general_response.sub_events,
            post_text=post_text,
            raw_message_id=raw_message_id,
        )
        normalized_sub_events: list[ExtractionSubEvent] = []
        for sub_event in sub_events:
            (
                _event_villages,
                event_locations,
                event_alternatives,
                event_evidence,
            ) = self._collapse_fuzzy_area_locations(
                sub_event.evidence_span or post_text,
                [entry.village for entry in sub_event.locations],
                sub_event.locations,
            )
            if event_alternatives:
                location_alternatives.extend(
                    item
                    for item in event_alternatives
                    if item not in location_alternatives
                )
                location_ambiguity_evidence = (
                    location_ambiguity_evidence or event_evidence
                )
            normalized_sub_events.append(
                sub_event.model_copy(update={"locations": event_locations})
            )
        sub_events = normalized_sub_events
        scope, scope_evidence, scope_needs_review, scope_reason = (
            self._validated_casualty_scope(
                general_response,
                village_roles=village_roles,
                post_text=post_text,
                raw_message_id=raw_message_id,
            )
        )
        needs_review, review_reason = self._multi_village_action_scope_review(
            post_text,
            village_roles=village_roles,
            sub_events=sub_events,
        )

        return ExtractionResult(
            is_relevant=general_response.is_relevant,
            village=villages,
            village_roles=village_roles,
            location_ambiguity=bool(location_alternatives),
            location_alternatives=location_alternatives,
            location_ambiguity_evidence=location_ambiguity_evidence,
            action_description=self._validated_text(
                general_response.action_description,
                field_name="action_description",
                raw_message_id=raw_message_id,
            ),
            sub_events=sub_events,
            categories=categories,
            casualties=casualties,
            casualty_evidence=casualty_evidence,
            casualty_transitions=list(general_response.casualty_transitions),
            casualty_scope=scope,
            casualty_scope_evidence=scope_evidence,
            casualty_scope_needs_review=scope_needs_review,
            casualty_scope_review_reason=scope_reason,
            needs_review=needs_review,
            review_reason=review_reason,
            presence_category_keys=list(categories_present),
            extraction_tier=1,
            model=self.client.model,
            extracted_at=datetime.now(timezone.utc),
        )

    @classmethod
    def _multi_village_action_scope_review(
        cls,
        post_text: str,
        *,
        village_roles: list[VillageRoleEntry],
        sub_events: list[ExtractionSubEvent],
    ) -> tuple[bool, str | None]:
        if sub_events:
            return False, None
        target_names = []
        seen: set[str] = set()
        for role in village_roles:
            if role.role != VillageRole.target:
                continue
            key = normalize_arabic_text(role.village, compact=True).lower()
            if not key or key in seen:
                continue
            seen.add(key)
            target_names.append(role.village)
        if len(target_names) < 2:
            return False, None

        families_by_village: dict[str, frozenset[str]] = {}
        for village in target_names:
            families = cls._action_families_near_village(post_text, village)
            if families:
                families_by_village[village] = families
        distinct_families = set(families_by_village.values())
        if len(distinct_families) >= 2:
            return True, MULTI_VILLAGE_NO_SUBEVENTS_REVIEW_REASON
        return False, None

    @classmethod
    def _action_families_near_village(cls, text: str, village: str) -> frozenset[str]:
        normalized_text = normalize_arabic_text(text).lower()
        normalized_village = normalize_arabic_text(village).lower()
        if not normalized_village:
            return frozenset()
        families: set[str] = set()
        for clause in re.split(r"[\n.،؛;!؟]+", normalized_text):
            if normalized_village not in clause:
                continue
            for family, terms in _ACTION_FAMILIES:
                if any(normalize_arabic_text(term).lower() in clause for term in terms):
                    families.add(family)
        return frozenset(families)

    def extract_tier2_details(
        self,
        post_text: str,
        presence_category_keys: list[ExtractionCategoryKey],
        *,
        root_casualties: ExtractionCasualties | None = None,
        raw_message_id: int | None = None,
    ) -> dict[ExtractionCategoryKey, ExtractionCategory]:
        """Run Tier-2 category detail extraction for keys detected in Tier 1."""
        if not presence_category_keys:
            return {}

        if settings.tier2_use_batched_category_detail:
            return self._extract_tier2_details_batched(
                post_text,
                presence_category_keys,
                root_casualties=root_casualties,
                raw_message_id=raw_message_id,
            )

        category_details: dict[str, ExtractionCategory] = {}
        failed_categories: list[str] = []
        last_error: BaseException | None = None
        for category_key in presence_category_keys:
            try:
                category_detail = self.category_detail.extract_detail(
                    post_text,
                    category_key=category_key,
                    raw_message_id=raw_message_id,
                )
            except Exception as exc:
                auth_failure = coerce_ollama_auth_failure(
                    exc,
                    stage="tier2_detail_fill",
                )
                if auth_failure is not None:
                    raise auth_failure from exc
                message = str(exc).strip()
                error = (
                    f"{type(exc).__name__}: {message}"
                    if message
                    else f"{type(exc).__name__} (no message)"
                )
                logger.exception(
                    "Failed to extract category detail category=%s "
                    "raw_message_id=%s error=%s",
                    category_key.value,
                    raw_message_id,
                    error,
                )
                failed_categories.append(category_key.value)
                last_error = exc
                continue

            if self._is_empty_category_detail(category_detail):
                logger.warning(
                    "Dropped empty category detail category=%s raw_message_id=%s",
                    category_key.value,
                    raw_message_id,
                )
                continue

            category_details[category_key.value] = category_detail

        if failed_categories:
            logger.error(
                "Tier2 category extraction incomplete raw_message_id=%s "
                "failed_categories=%s succeeded_categories=%s",
                raw_message_id,
                failed_categories,
                list(category_details.keys()),
            )
            # A failed LLM call is not an empty answer: finalizing a partial
            # result would permanently drop the failed categories.
            raise Tier2ExtractionFailedError(failed_categories, last_error)

        return self._finalize_tier2_categories(
            category_details,
            root_casualties=root_casualties,
            raw_message_id=raw_message_id,
        )

    def _extract_tier2_details_batched(
        self,
        post_text: str,
        presence_category_keys: list[ExtractionCategoryKey],
        *,
        root_casualties: ExtractionCasualties | None,
        raw_message_id: int | None,
    ) -> dict[ExtractionCategoryKey, ExtractionCategory]:
        try:
            batched = self.category_detail.extract_details_batch(
                post_text,
                presence_category_keys,
                raw_message_id=raw_message_id,
            )
        except Exception as exc:
            auth_failure = coerce_ollama_auth_failure(
                exc,
                stage="tier2_detail_fill",
            )
            if auth_failure is not None:
                raise auth_failure from exc
            logger.exception(
                "Failed batched Tier2 category extraction raw_message_id=%s error=%s",
                raw_message_id,
                exc,
            )
            raise Tier2ExtractionFailedError(
                [key.value for key in presence_category_keys],
                exc,
            ) from exc

        category_details: dict[str, ExtractionCategory] = {}
        for category_key in presence_category_keys:
            category_detail = batched.get(category_key)
            if category_detail is None:
                logger.warning(
                    "Batched Tier2 missing category=%s raw_message_id=%s",
                    category_key.value,
                    raw_message_id,
                )
                continue
            if self._is_empty_category_detail(category_detail):
                logger.warning(
                    "Dropped empty batched category detail category=%s "
                    "raw_message_id=%s",
                    category_key.value,
                    raw_message_id,
                )
                continue
            category_details[category_key.value] = category_detail

        return self._finalize_tier2_categories(
            category_details,
            root_casualties=root_casualties,
            raw_message_id=raw_message_id,
        )

    def _finalize_tier2_categories(
        self,
        category_details: dict[str, ExtractionCategory],
        *,
        root_casualties: ExtractionCasualties | None,
        raw_message_id: int | None,
    ) -> dict[ExtractionCategoryKey, ExtractionCategory]:
        categories = self._validated_categories(
            category_details,
            raw_message_id=raw_message_id,
        )
        if root_casualties is not None:
            self._inject_casualty_demographics_from_root(categories, root_casualties)
        return categories

    def extract(
        self,
        post_text: str,
        raw_message_id: int | None = None,
    ) -> ExtractionResult:
        categories_present = self.presence_gate.categories_present(
            post_text,
            raw_message_id=raw_message_id,
        )
        general_response = self._extract_general_fields(
            post_text,
            raw_message_id=raw_message_id,
        )
        category_details: dict[str, ExtractionCategory] = {}
        failed_categories: list[str] = []
        for category_key in categories_present:
            try:
                category_detail = self.category_detail.extract_detail(
                    post_text,
                    category_key=category_key,
                    raw_message_id=raw_message_id,
                )
            except Exception as exc:
                auth_failure = coerce_ollama_auth_failure(
                    exc,
                    stage="tier2_detail_fill",
                )
                if auth_failure is not None:
                    raise auth_failure from exc
                message = str(exc).strip()
                error = (
                    f"{type(exc).__name__}: {message}"
                    if message
                    else f"{type(exc).__name__} (no message)"
                )
                logger.exception(
                    "Failed to extract category detail category=%s "
                    "raw_message_id=%s error=%s",
                    category_key.value,
                    raw_message_id,
                    error,
                )
                failed_categories.append(category_key.value)
                continue

            if self._is_empty_category_detail(category_detail):
                logger.warning(
                    "Dropped empty category detail category=%s raw_message_id=%s",
                    category_key.value,
                    raw_message_id,
                )
                continue

            category_details[category_key.value] = category_detail
        if failed_categories:
            logger.error(
                "Tier1 category extraction incomplete raw_message_id=%s "
                "failed_categories=%s succeeded_categories=%s",
                raw_message_id,
                failed_categories,
                list(category_details.keys()),
            )
        result = self._build_tier1_result(
            post_text=post_text,
            categories_present=list(categories_present),
            general_response=general_response,
            raw_message_id=raw_message_id,
        )
        categories = self._validated_categories(
            category_details,
            raw_message_id=raw_message_id,
        )
        self._inject_casualty_demographics_from_root(
            categories,
            result.casualties,
        )
        return result.model_copy(
            update={
                "categories": categories,
                "extraction_tier": 2,
            }
        )

    def _extract_general_fields(
        self,
        post_text: str,
        raw_message_id: int | None,
    ) -> _RawExtractionResponse:
        content = self.client.chat(
            [
                OllamaChatMessage(
                    role="system",
                    content=build_stage_system_prompt("tier1_extraction", post_text),
                ),
                OllamaChatMessage(role="user", content=post_text),
            ],
            response_format=GENERAL_EXTRACTION_RESPONSE_SCHEMA,
            temperature=LOW_TEMPERATURE,
        )
        return self._parse_general_response(content, raw_message_id=raw_message_id)

    def _parse_general_response(
        self,
        content: str,
        raw_message_id: int | None,
    ) -> _RawExtractionResponse:
        try:
            payload = json.loads(content.strip())
            response = _RawExtractionResponse.model_validate(payload)
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            logger.warning(
                "Malformed extraction response from model=%s for raw_message_id=%s: %s",
                self.client.model,
                raw_message_id,
                exc,
            )
            raise RuntimeError("Malformed extraction response.") from exc

        # Normalise village to list[str] regardless of whether the model returned
        # a string (old-format or non-compliant) or an array.
        village_raw = response.village
        if isinstance(village_raw, str):
            parts = [p.strip() for p in village_raw.split(",") if p.strip()]
            village_norm: list[str] | None = parts if parts else None
        elif isinstance(village_raw, list):
            village_norm = village_raw if village_raw else None
        else:
            village_norm = None

        if village_norm is not response.village:
            response = response.model_copy(update={"village": village_norm})

        return response

    def _validated_categories(
        self,
        categories: dict[str, ExtractionCategory],
        raw_message_id: int | None,
    ) -> dict[ExtractionCategoryKey, ExtractionCategory]:
        validated: dict[ExtractionCategoryKey, ExtractionCategory] = {}
        for raw_key, raw_category in categories.items():
            if raw_key not in ALLOWED_EXTRACTION_CATEGORY_KEYS:
                logger.warning(
                    "Dropped invalid extraction category for raw_message_id=%s: %s",
                    raw_message_id,
                    raw_key,
                )
                continue

            category_key = ExtractionCategoryKey(raw_key)
            validated[category_key] = ExtractionCategory(
                did=raw_category.did,
                name=self._validated_text(
                    raw_category.name,
                    field_name=f"categories.{raw_key}.name",
                    raw_message_id=raw_message_id,
                ),
                casualties=raw_category.casualties,
                vehicles=raw_category.vehicles,
            )
        return validated

    def _has_populated_casualties(self, casualties: ExtractionCasualties) -> bool:
        return any(
            value is not None and value != 0
            for value in casualties.model_dump(mode="python").values()
        )

    def _inject_casualty_demographics_from_root(
        self,
        categories: dict[ExtractionCategoryKey, ExtractionCategory],
        root_casualties: ExtractionCasualties,
    ) -> None:
        if not self._has_populated_casualties(root_casualties):
            return

        category_key = ExtractionCategoryKey.casualty_demographics
        if category_key in categories:
            return

        categories[category_key] = ExtractionCategory(
            did=None,
            name=None,
            casualties=root_casualties,
        )

    def _is_empty_category_detail(self, category: ExtractionCategory) -> bool:
        if category.did is not None or category.name is not None:
            return False
        if category.vehicles is not None and any(
            value
            for value in category.vehicles.model_dump(mode="python").values()
            if value is not None and value is not False
        ):
            return False
        if category.casualties is None:
            return True
        return all(
            value is None
            for value in category.casualties.model_dump(mode="python").values()
        )

    def _validated_village_list(
        self,
        villages: list[str] | None,
        raw_message_id: int | None,
    ) -> list[str] | None:
        if not villages:
            return None
        validated: list[str] = []
        for entry in villages:
            if is_valid_reason_text(entry):
                validated.append(entry)
            else:
                logger.warning(
                    "Invalid village text from model=%s for raw_message_id=%s",
                    self.client.model,
                    raw_message_id,
                )
                logger.debug(
                    "Rejected village text from model=%s for raw_message_id=%s: %r",
                    self.client.model,
                    raw_message_id,
                    entry,
                )
        return validated if validated else None

    def _validated_village_roles(
        self,
        village_roles: list[VillageRoleEntry],
        post_text: str,
        raw_message_id: int | None,
    ) -> list[VillageRoleEntry]:
        validated: list[VillageRoleEntry] = []
        for entry in village_roles:
            if is_valid_reason_text(entry.village):
                evidence_span = self._validated_text(
                    entry.evidence_span,
                    field_name="village_roles.evidence_span",
                    raw_message_id=raw_message_id,
                )
                if evidence_span is not None and evidence_span not in post_text:
                    logger.warning(
                        "Dropped non-source village casualty evidence for "
                        "raw_message_id=%s village=%s",
                        raw_message_id,
                        entry.village,
                    )
                    evidence_span = None
                qualifier_text = self._validated_text(
                    entry.qualifier_text,
                    field_name="village_roles.qualifier_text",
                    raw_message_id=raw_message_id,
                )
                if qualifier_text is not None and qualifier_text not in post_text:
                    qualifier_text = None

                evidence = (
                    [
                        CasualtyCountEvidence(
                            field=field,
                            evidence_span=evidence_span,
                        )
                        for field, value in (
                            ("deaths", entry.deaths),
                            ("injuries", entry.injuries),
                        )
                        if value is not None and evidence_span is not None
                    ]
                    if evidence_span is not None
                    else []
                )
                village_casualties, _ = apply_casualty_count_backstop(
                    evidence_span or "",
                    ExtractionCasualties(
                        deaths=entry.deaths,
                        injuries=entry.injuries,
                    ),
                    evidence,
                    raw_message_id=raw_message_id,
                )
                validated.append(
                    entry.model_copy(
                        update={
                            "deaths": village_casualties.deaths,
                            "injuries": village_casualties.injuries,
                            "evidence_span": evidence_span,
                            "qualifier_text": qualifier_text,
                        }
                    )
                )
            else:
                logger.warning(
                    "Invalid village_roles.village text from model=%s for raw_message_id=%s",
                    self.client.model,
                    raw_message_id,
                )
                logger.debug(
                    "Rejected village_roles entry from model=%s for raw_message_id=%s: %r",
                    self.client.model,
                    raw_message_id,
                    entry.model_dump(mode="json"),
                )
        return validated

    def _validated_sub_events(
        self,
        sub_events: list[ExtractionSubEvent],
        *,
        post_text: str,
        raw_message_id: int | None,
    ) -> list[ExtractionSubEvent]:
        validated: list[ExtractionSubEvent] = []
        for index, sub_event in enumerate(sub_events):
            locations = self._validated_village_roles(
                sub_event.locations,
                post_text=post_text,
                raw_message_id=raw_message_id,
            )
            _location_names, locations = self._apply_dash_compound_location_rules(
                sub_event.evidence_span or post_text,
                [entry.village for entry in locations],
                locations,
            )
            if not locations:
                logger.warning(
                    "Dropped locationless sub_event index=%s raw_message_id=%s",
                    index,
                    raw_message_id,
                )
                continue
            evidence_span = self._validated_source_span(
                sub_event.evidence_span,
                post_text=post_text,
                field_name=f"sub_events[{index}].evidence_span",
                raw_message_id=raw_message_id,
            )
            casualty_text = evidence_span or post_text
            casualties, casualty_evidence = apply_casualty_count_backstop(
                casualty_text,
                sub_event.casualties,
                list(sub_event.casualty_evidence),
                raw_message_id=raw_message_id,
            )
            validated.append(
                sub_event.model_copy(
                    update={
                        "locations": locations,
                        "action_text": self._validated_text(
                            sub_event.action_text,
                            field_name=f"sub_events[{index}].action_text",
                            raw_message_id=raw_message_id,
                        ),
                        "casualties": casualties,
                        "casualty_evidence": casualty_evidence,
                        "evidence_span": evidence_span,
                    }
                )
            )
        return validated

    @classmethod
    def _apply_dash_compound_location_rules(
        cls,
        post_text: str,
        villages: list[str] | None,
        village_roles: list[VillageRoleEntry],
    ) -> tuple[list[str] | None, list[VillageRoleEntry]]:
        villages, village_roles = cls._apply_dash_route_village_backstop(
            post_text,
            villages,
            village_roles,
        )
        for match in _DASH_QUALIFIER_RE.finditer(post_text):
            villages, village_roles = cls._apply_dash_qualifier_backstop(
                match,
                villages,
                village_roles,
            )
        villages, village_roles = cls._recover_secondary_strike_location(
            post_text,
            villages,
            village_roles,
        )
        villages, village_roles = cls._recover_connector_event_villages(
            post_text,
            villages,
            village_roles,
        )
        villages, village_roles = cls._recover_baldat_list_villages(
            post_text,
            villages,
            village_roles,
        )
        villages, village_roles = cls._recover_missing_balda_villages(
            post_text,
            villages,
            village_roles,
        )
        return villages, village_roles

    @staticmethod
    def _merge_recovered_villages(
        villages: list[str] | None,
        village_roles: list[VillageRoleEntry],
        recovered: list[str],
    ) -> tuple[list[str] | None, list[VillageRoleEntry]]:
        if not recovered:
            return villages, village_roles
        existing_names = list(villages or [])
        existing_names.extend(entry.village for entry in village_roles)
        existing_norms = {
            normalize_arabic_text(name)
            for name in existing_names
            if normalize_arabic_text(name)
        }
        merged_villages = list(villages or [])
        merged_roles = list(village_roles)
        for village in recovered:
            normalized = normalize_arabic_text(village)
            if not normalized or normalized in existing_norms:
                continue
            if normalized in {"البلدة", "بلدة", "بلدات"}:
                continue
            existing_norms.add(normalized)
            merged_villages.append(village)
            merged_roles.append(
                VillageRoleEntry(village=village, role=VillageRole.target)
            )
        return merged_villages or villages, merged_roles

    @staticmethod
    def _split_arabic_place_list(body: str) -> list[str]:
        text = body.strip().strip("،,")
        if not text:
            return []
        # Final «و» before the last place: «الخردلي ويارون» (often no space after و)
        text = re.sub(r"\s+و\s*", "، ", text)
        parts: list[str] = []
        seen: set[str] = set()
        for raw in re.split(r"[،,]", text):
            place = raw.strip().strip("،,")
            normalized = normalize_arabic_text(place)
            if not normalized or normalized in seen:
                continue
            if normalized in {"البلدة", "بلدة", "بلدات"}:
                continue
            seen.add(normalized)
            parts.append(place)
        return parts

    @classmethod
    def _recover_baldat_list_villages(
        cls,
        post_text: str,
        villages: list[str] | None,
        village_roles: list[VillageRoleEntry],
    ) -> tuple[list[str] | None, list[VillageRoleEntry]]:
        """Recover every named place in a «بلدات A، B، C وD» bulletin list.

        ACCSTUDY-003-style aggregates name many villages in one ``بلدات`` clause;
        the model (and the single-balda backstop) often keep only the first.
        """
        match = _BALDAT_LIST_RE.search(post_text or "")
        if match is None:
            return villages, village_roles
        recovered = cls._split_arabic_place_list(match.group("body"))
        if len(recovered) < 2:
            return villages, village_roles
        return cls._merge_recovered_villages(villages, village_roles, recovered)

    @classmethod
    def _recover_connector_event_villages(
        cls,
        post_text: str,
        villages: list[str] | None,
        village_roles: list[VillageRoleEntry],
    ) -> tuple[list[str] | None, list[VillageRoleEntry]]:
        """Recover villages introduced by كما/أيضا-style event connectors.

        ACCSTUDY-002: «كما غارة أخرى في بلدة عيناتا» / «كما غارة أخرى في بلدة طيرحرفا».
        """
        recovered = [
            match.group("village").strip()
            for match in _SECONDARY_EVENT_CONNECTOR_RE.finditer(post_text or "")
            if match.group("village") and match.group("village").strip()
        ]
        return cls._merge_recovered_villages(villages, village_roles, recovered)

    @staticmethod
    def _recover_missing_balda_villages(
        post_text: str,
        villages: list[str] | None,
        village_roles: list[VillageRoleEntry],
    ) -> tuple[list[str] | None, list[VillageRoleEntry]]:
        """Recover explicit «بلدة/بلدات X» when the model left village null/empty.

        ACCSTUDY-001: the model returned village=null for
        «استهداف ... لسيارة في بلدة دبل» even though the place phrase is
        unambiguous. Matching cannot alias a missing extraction.
        """
        if villages:
            return villages, village_roles
        if any(entry.village.strip() for entry in village_roles):
            return villages, village_roles

        recovered: list[str] = []
        seen: set[str] = set()
        for match in _BALDA_VILLAGE_RE.finditer(post_text):
            village = match.group("village").strip().strip("،؛")
            # Truncate list connectors: «بلدات حولا ومارون» -> حولا only here;
            # multi-village fan-out remains a Tier-1 model responsibility.
            for connector in (" و", "،", " و "):
                if connector in village:
                    village = village.split(connector, 1)[0].strip()
            normalized = normalize_arabic_text(village)
            if not normalized or normalized in seen:
                continue
            # Skip bare administrative words mistaken for place names.
            if normalized in {"البلدة", "بلدة", "بلدات"}:
                continue
            seen.add(normalized)
            recovered.append(village)

        if not recovered:
            return villages, village_roles

        merged_roles = list(village_roles)
        existing_role_norms = {
            normalize_arabic_text(entry.village) for entry in merged_roles
        }
        for village in recovered:
            if normalize_arabic_text(village) in existing_role_norms:
                continue
            merged_roles.append(
                VillageRoleEntry(village=village, role=VillageRole.target)
            )
        return recovered, merged_roles

    @staticmethod
    def _recover_secondary_strike_location(
        post_text: str,
        villages: list[str] | None,
        village_roles: list[VillageRoleEntry],
    ) -> tuple[list[str] | None, list[VillageRoleEntry]]:
        """Recover a second target dropped after a distinct-event connector.

        "كما طال القصف ... بلدة X" explicitly introduces a separately scoped
        strike location, unlike a محيط/بين vicinity phrase describing one
        fuzzy place — this must never be collapsed the way
        ``_collapse_fuzzy_area_locations`` collapses those.
        """
        match = _SECONDARY_STRIKE_RE.search(post_text)
        if match is None:
            return villages, village_roles

        village = match.group("village").strip()
        if not village:
            return villages, village_roles

        existing_names = list(villages or [])
        existing_names.extend(entry.village for entry in village_roles)
        existing_norms = {
            normalize_arabic_text(name)
            for name in existing_names
            if normalize_arabic_text(name)
        }
        if normalize_arabic_text(village) in existing_norms:
            return villages, village_roles

        merged_villages = list(villages or [])
        merged_villages.append(village)
        merged_roles = list(village_roles)
        merged_roles.append(
            VillageRoleEntry(village=village, role=VillageRole.target)
        )
        return merged_villages, merged_roles

    @staticmethod
    def _collapse_fuzzy_area_locations(
        post_text: str,
        villages: list[str] | None,
        village_roles: list[VillageRoleEntry],
    ) -> tuple[list[str] | None, list[VillageRoleEntry], list[str], str | None]:
        """Collapse hedged multi-place wording to one reviewable location."""
        normalized_text = normalize_arabic_text(post_text or "")
        marker = re.search(
            r"(?:في\s+)?(?:محيط|قرب|بالقرب\s+من|بين)\s+",
            normalized_text,
        )
        if marker is None:
            return villages, village_roles, [], None
        if normalized_text[max(0, marker.start() - 12) : marker.start()].find(
            "طريق"
        ) >= 0:
            return villages, village_roles, [], None

        tail = normalized_text[marker.end() :]
        tail = re.split(r"[،؛.!؟\n]", tail, maxsplit=1)[0]
        entries = list(village_roles)
        if not entries:
            entries = [VillageRoleEntry(village=name) for name in villages or []]
        ordered = sorted(
            (
                entry
                for entry in entries
                if normalize_arabic_text(entry.village)
                and normalize_arabic_text(entry.village) in tail
            ),
            key=lambda entry: tail.find(normalize_arabic_text(entry.village)),
        )
        if len(ordered) < 2:
            return villages, village_roles, [], None

        primary = ordered[0]
        alternatives = [entry.village for entry in ordered[1:]]
        evidence = normalized_text[marker.start() :].split(".", 1)[0].strip()
        collapsed = primary.model_copy(
            update={
                "evidence_span": primary.evidence_span or evidence,
                "qualifier_text": primary.qualifier_text
                or f"fuzzy area; alternate: {', '.join(alternatives)}",
            }
        )
        # Only replace the fuzzy group itself — other, unrelated locations
        # already extracted (e.g. a distinct second strike introduced by a
        # "كما طال القصف" connector elsewhere in the same bulletin) must
        # survive the collapse rather than being silently dropped.
        collapsed_ids = {id(entry) for entry in ordered}
        unaffected = [entry for entry in entries if id(entry) not in collapsed_ids]
        new_roles = [collapsed] + unaffected
        new_villages = [primary.village] + [entry.village for entry in unaffected]
        return new_villages, new_roles, alternatives, evidence

    @staticmethod
    def _apply_dash_route_village_backstop(
        post_text: str,
        villages: list[str] | None,
        village_roles: list[VillageRoleEntry],
    ) -> tuple[list[str] | None, list[VillageRoleEntry]]:
        """Recover both endpoints when a model drops one dash-joined route place."""
        match = _DASH_ROUTE_RE.search(post_text) or _BETWEEN_ROUTE_RE.search(post_text)
        if match is None:
            return villages, village_roles

        left = match.group("left").strip()
        for prefix in _ROUTE_AREA_PREFIXES:
            if left.startswith(prefix):
                left = left[len(prefix) :].strip()
                break
        right = match.group("right").strip()
        if not left or not right:
            return villages, village_roles

        existing_names = list(villages or [])
        existing_names.extend(entry.village for entry in village_roles)
        existing_norms = {
            normalize_arabic_text(name)
            for name in existing_names
            if normalize_arabic_text(name)
        }
        endpoint_norms = {
            normalize_arabic_text(left),
            normalize_arabic_text(right),
        }
        # Do not invent two locations from arbitrary dash punctuation. At least
        # one endpoint must already have been recognized by the model.
        if not existing_norms.intersection(endpoint_norms):
            return villages, village_roles

        merged_villages = list(villages or [])
        merged_norms = {
            normalize_arabic_text(name)
            for name in merged_villages
            if normalize_arabic_text(name)
        }
        merged_roles = list(village_roles)
        role_norms = {
            normalize_arabic_text(entry.village)
            for entry in merged_roles
            if normalize_arabic_text(entry.village)
        }
        for endpoint in (left, right):
            normalized = normalize_arabic_text(endpoint)
            if normalized not in merged_norms:
                merged_villages.append(endpoint)
                merged_norms.add(normalized)
            if normalized not in role_norms:
                merged_roles.append(
                    VillageRoleEntry(village=endpoint, role=VillageRole.target)
                )
                role_norms.add(normalized)
        return merged_villages, merged_roles

    @staticmethod
    def _apply_dash_qualifier_backstop(
        match: re.Match[str],
        villages: list[str] | None,
        village_roles: list[VillageRoleEntry],
    ) -> tuple[list[str] | None, list[VillageRoleEntry]]:
        """Collapse a non-route dash phrase to one target plus qualifier."""
        prefix = match.group("prefix").strip()
        left = match.group("left").strip()
        right = match.group("right").strip()
        if not left or not right:
            return villages, village_roles

        target = f"{prefix} {left}" if prefix == "مزرعة" else left
        target_norm = normalize_arabic_text(target)
        left_norm = normalize_arabic_text(left)
        right_norm = normalize_arabic_text(right)
        right_parts = {
            part.strip() for part in re.split(r"\s+و(?=\S)", right_norm) if part.strip()
        }

        def is_left(value: str) -> bool:
            normalized = normalize_arabic_text(value)
            return bool(
                normalized
                and (
                    normalized in {left_norm, target_norm}
                    or target_norm.endswith(f" {normalized}")
                    or normalized.startswith(f"{target_norm} ")
                )
            )

        def is_qualifier(value: str) -> bool:
            normalized = normalize_arabic_text(value)
            return bool(
                normalized
                and (
                    normalized == right_norm
                    or any(
                        normalized == part
                        or part.endswith(f" {normalized}")
                        or normalized.endswith(f" {part}")
                        for part in right_parts
                    )
                )
            )

        existing_names = list(villages or [])
        existing_names.extend(entry.village for entry in village_roles)
        if not any(is_left(name) or is_qualifier(name) for name in existing_names):
            return villages, village_roles

        merged_villages: list[str] = []
        target_added = False
        for name in villages or []:
            if is_qualifier(name):
                continue
            if is_left(name):
                if not target_added:
                    merged_villages.append(target)
                    target_added = True
                continue
            merged_villages.append(name)
        if not target_added:
            merged_villages.append(target)

        merged_roles: list[VillageRoleEntry] = []
        target_role_added = False
        for entry in village_roles:
            if is_qualifier(entry.village):
                continue
            if is_left(entry.village):
                if not target_role_added:
                    merged_roles.append(
                        entry.model_copy(
                            update={
                                "village": target,
                                "qualifier_text": right,
                            }
                        )
                    )
                    target_role_added = True
                continue
            merged_roles.append(entry)
        if not target_role_added:
            merged_roles.append(
                VillageRoleEntry(
                    village=target,
                    role=VillageRole.target,
                    qualifier_text=right,
                )
            )
        return merged_villages or None, merged_roles

    def _validated_text(
        self,
        value: str | None,
        field_name: str,
        raw_message_id: int | None,
    ) -> str | None:
        if value is None:
            return None
        if is_valid_reason_text(value):
            return value

        logger.warning(
            "Invalid extraction text field=%s from model=%s for raw_message_id=%s",
            field_name,
            self.client.model,
            raw_message_id,
        )
        logger.debug(
            "Rejected extraction text field=%s from model=%s for raw_message_id=%s: %r",
            field_name,
            self.client.model,
            raw_message_id,
            value,
        )
        return None

    def _validated_source_span(
        self,
        value: str | None,
        *,
        post_text: str,
        field_name: str,
        raw_message_id: int | None,
    ) -> str | None:
        span = self._validated_text(
            value,
            field_name=field_name,
            raw_message_id=raw_message_id,
        )
        if span is None or span in post_text:
            return span
        logger.warning(
            "Dropped non-source extraction span field=%s raw_message_id=%s",
            field_name,
            raw_message_id,
        )
        return None

    def _validated_casualty_scope(
        self,
        response: _RawExtractionResponse,
        *,
        village_roles: list[VillageRoleEntry],
        post_text: str,
        raw_message_id: int | None,
    ) -> tuple[CasualtyScope, str | None, bool, str | None]:
        evidence = self._validated_source_span(
            response.casualty_scope_evidence,
            post_text=post_text,
            field_name="casualty_scope_evidence",
            raw_message_id=raw_message_id,
        )
        result = validate_casualty_scope(
            casualty_scope=response.casualty_scope,
            evidence=evidence,
            village_roles=village_roles,
            aliases_by_village=self.casualty_scope_aliases,
        )
        if result.plausible:
            return response.casualty_scope, evidence, False, None

        reason = (
            f"Unsupported casualty_scope={response.casualty_scope.value}: "
            f"evidence matched {result.village_count_in_evidence} target village(s)"
        )
        logger.warning("%s raw_message_id=%s", reason, raw_message_id)
        return CasualtyScope.unspecified, evidence, True, reason
