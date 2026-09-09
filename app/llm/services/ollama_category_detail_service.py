from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.ollama_client import JsonObject, OllamaChatClient, OllamaChatMessage
from app.llm.dtos import (
    CasualtyCountEvidence,
    DidValue,
    ExtractionCasualties,
    ExtractionCategory,
    ExtractionCategoryKey,
    ExtractionVehicleDetails,
)
from app.llm.services.ollama_presence_gate_service import LOW_TEMPERATURE
from app.llm.services.ollama_relevance_classifier_service import is_valid_reason_text
from app.news.services.incident_details.casualty_count_backstop import (
    apply_casualty_count_backstop,
)

logger = logging.getLogger(__name__)

_MOTORCYCLE_TEXT_MARKERS = ("دراج", "موتور")


def _ground_motorcycle_flag(
    post_text: str,
    vehicles: ExtractionVehicleDetails | None,
) -> ExtractionVehicleDetails | None:
    """Preserve an explicit Arabic motorcycle mention if the model misses it."""
    if not any(marker in post_text for marker in _MOTORCYCLE_TEXT_MARKERS):
        return vehicles
    if vehicles is None:
        return ExtractionVehicleDetails(moto=True)
    if vehicles.moto:
        return vehicles
    return vehicles.model_copy(update={"moto": True})


PROMPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "phase2-extraction-testing"
    / "category_detail_instruction.txt"
)
CATEGORY_DETAIL_PROMPT = PROMPT_PATH.read_text(encoding="utf-8")
BATCHED_PROMPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "phase2-extraction-testing"
    / "batched_category_detail_instruction.txt"
)
BATCHED_CATEGORY_DETAIL_PROMPT = BATCHED_PROMPT_PATH.read_text(encoding="utf-8")
_CATEGORY_KEY_ENUM = [
    category.value for category in ExtractionCategoryKey
]
CATEGORY_DETAIL_RESPONSE_SCHEMA: JsonObject = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "did": {"type": ["string", "null"], "enum": ["D", "ID", None]},
        "name": {"type": ["string", "null"]},
        "casualties": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "properties": {
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
        "casualty_evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "field": {
                        "type": "string",
                        "enum": [
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
        "vehicles": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "properties": {
                "car": {"type": ["boolean", "null"]},
                "moto": {"type": ["boolean", "null"]},
                "con_veh": {"type": ["boolean", "null"]},
                "excavator": {"type": ["boolean", "null"]},
                "bulldozer": {"type": ["boolean", "null"]},
                "camion": {"type": ["boolean", "null"]},
                "bobcat": {"type": ["boolean", "null"]},
                "tracteur": {"type": ["boolean", "null"]},
                "con_d": {"type": ["integer", "null"]},
                "con_i": {"type": ["integer", "null"]},
                "moto_d": {"type": ["integer", "null"]},
                "moto_i": {"type": ["integer", "null"]},
            },
        },
    },
    "required": ["did", "name"],
}

_BATCHED_CATEGORY_DETAIL_ITEM_SCHEMA: JsonObject = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "category_key": {"type": "string", "enum": _CATEGORY_KEY_ENUM},
        **CATEGORY_DETAIL_RESPONSE_SCHEMA["properties"],  # type: ignore[arg-type]
    },
    "required": ["category_key", "did", "name"],
}

BATCHED_CATEGORY_DETAIL_RESPONSE_SCHEMA: JsonObject = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "category_details": {
            "type": "array",
            "items": _BATCHED_CATEGORY_DETAIL_ITEM_SCHEMA,
        }
    },
    "required": ["category_details"],
}


class _RawCategoryDetailResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    did: DidValue | None = None
    name: str | None = None
    casualties: ExtractionCasualties | None = None
    casualty_evidence: list[CasualtyCountEvidence] = Field(default_factory=list)
    vehicles: ExtractionVehicleDetails | None = None


class _RawBatchedCategoryDetailItem(_RawCategoryDetailResponse):
    category_key: str


class _RawBatchedCategoryDetailResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    category_details: list[_RawBatchedCategoryDetailItem] = Field(default_factory=list)


class OllamaCategoryDetailService:
    def __init__(self, client: OllamaChatClient) -> None:
        self.client = client

    def extract_detail(
        self,
        post_text: str,
        category_key: ExtractionCategoryKey,
        raw_message_id: int | None = None,
    ) -> ExtractionCategory:
        content = self.client.chat(
            [
                OllamaChatMessage(role="system", content=CATEGORY_DETAIL_PROMPT),
                OllamaChatMessage(
                    role="user",
                    content=(
                        f"category_key: {category_key.value}\n\n"
                        f"النص:\n{post_text}"
                    ),
                ),
            ],
            response_format=CATEGORY_DETAIL_RESPONSE_SCHEMA,
            temperature=LOW_TEMPERATURE,
        )
        return self._parse_response(
            content,
            post_text=post_text,
            category_key=category_key,
            raw_message_id=raw_message_id,
        )

    def extract_details_batch(
        self,
        post_text: str,
        category_keys: list[ExtractionCategoryKey],
        raw_message_id: int | None = None,
    ) -> dict[ExtractionCategoryKey, ExtractionCategory]:
        if not category_keys:
            return {}

        keys_csv = ", ".join(key.value for key in category_keys)
        content = self.client.chat(
            [
                OllamaChatMessage(role="system", content=BATCHED_CATEGORY_DETAIL_PROMPT),
                OllamaChatMessage(
                    role="user",
                    content=(
                        f"category_keys: [{keys_csv}]\n\n"
                        f"النص:\n{post_text}"
                    ),
                ),
            ],
            response_format=BATCHED_CATEGORY_DETAIL_RESPONSE_SCHEMA,
            temperature=LOW_TEMPERATURE,
        )
        return self._parse_batched_response(
            content,
            post_text=post_text,
            category_keys=category_keys,
            raw_message_id=raw_message_id,
        )

    def _parse_batched_response(
        self,
        content: str,
        *,
        post_text: str,
        category_keys: list[ExtractionCategoryKey],
        raw_message_id: int | None,
    ) -> dict[ExtractionCategoryKey, ExtractionCategory]:
        try:
            payload = json.loads(content.strip())
            response = _RawBatchedCategoryDetailResponse.model_validate(payload)
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            logger.warning(
                "Malformed batched category detail response from model=%s "
                "for raw_message_id=%s: %s",
                self.client.model,
                raw_message_id,
                exc,
            )
            raise RuntimeError("Malformed batched category detail response.") from exc

        allowed = {key.value for key in category_keys}
        parsed: dict[ExtractionCategoryKey, ExtractionCategory] = {}
        for item in response.category_details:
            if item.category_key not in allowed:
                logger.warning(
                    "Dropped unexpected batched category for raw_message_id=%s: %s",
                    raw_message_id,
                    item.category_key,
                )
                continue
            category_key = ExtractionCategoryKey(item.category_key)
            casualties = None
            if item.casualties is not None:
                casualties, _ = apply_casualty_count_backstop(
                    post_text,
                    item.casualties,
                    list(item.casualty_evidence),
                    raw_message_id=raw_message_id,
                )
            vehicles = item.vehicles
            if category_key == ExtractionCategoryKey.vehicles:
                vehicles = _ground_motorcycle_flag(post_text, vehicles)
            parsed[category_key] = ExtractionCategory(
                did=item.did,
                name=self._validated_name(
                    item.name,
                    category_key=category_key,
                    raw_message_id=raw_message_id,
                ),
                casualties=casualties,
                vehicles=vehicles,
            )
        return parsed

    def _parse_response(
        self,
        content: str,
        *,
        post_text: str,
        category_key: ExtractionCategoryKey,
        raw_message_id: int | None,
    ) -> ExtractionCategory:
        try:
            payload = json.loads(content.strip())
            response = _RawCategoryDetailResponse.model_validate(payload)
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            logger.warning(
                "Malformed category detail response from model=%s "
                "for category=%s raw_message_id=%s: %s",
                self.client.model,
                category_key.value,
                raw_message_id,
                exc,
            )
            raise RuntimeError("Malformed category detail response.") from exc

        casualties = None
        if response.casualties is not None:
            casualties, _ = apply_casualty_count_backstop(
                post_text,
                response.casualties,
                list(response.casualty_evidence),
                raw_message_id=raw_message_id,
            )
        vehicles = response.vehicles
        if category_key == ExtractionCategoryKey.vehicles:
            vehicles = _ground_motorcycle_flag(post_text, vehicles)
        return ExtractionCategory(
            did=response.did,
            name=self._validated_name(
                response.name,
                category_key=category_key,
                raw_message_id=raw_message_id,
            ),
            casualties=casualties,
            vehicles=vehicles,
        )

    def _validated_name(
        self,
        value: str | None,
        category_key: ExtractionCategoryKey,
        raw_message_id: int | None,
    ) -> str | None:
        if value is None:
            return None
        if is_valid_reason_text(value):
            return value

        logger.warning(
            "Invalid category detail name from model=%s for category=%s "
            "raw_message_id=%s",
            self.client.model,
            category_key.value,
            raw_message_id,
        )
        logger.debug(
            "Rejected category detail name from model=%s for category=%s "
            "raw_message_id=%s: %r",
            self.client.model,
            category_key.value,
            raw_message_id,
            value,
        )
        return None
