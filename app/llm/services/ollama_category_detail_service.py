from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.ollama_client import JsonObject, OllamaChatClient, OllamaChatMessage
from app.llm.dtos import (
    DidValue,
    ExtractionCasualties,
    ExtractionCategory,
    ExtractionCategoryKey,
    ExtractionVehicleDetails,
)
from app.llm.services.ollama_presence_gate_service import LOW_TEMPERATURE
from app.llm.services.ollama_relevance_classifier_service import is_valid_reason_text

logger = logging.getLogger(__name__)

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
            category_keys=category_keys,
            raw_message_id=raw_message_id,
        )

    def _parse_batched_response(
        self,
        content: str,
        *,
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
            parsed[category_key] = ExtractionCategory(
                did=item.did,
                name=self._validated_name(
                    item.name,
                    category_key=category_key,
                    raw_message_id=raw_message_id,
                ),
                casualties=item.casualties,
                vehicles=item.vehicles,
            )
        return parsed

    def _parse_response(
        self,
        content: str,
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

        return ExtractionCategory(
            did=response.did,
            name=self._validated_name(
                response.name,
                category_key=category_key,
                raw_message_id=raw_message_id,
            ),
            casualties=response.casualties,
            vehicles=response.vehicles,
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
