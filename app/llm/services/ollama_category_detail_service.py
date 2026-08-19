from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

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


class _RawCategoryDetailResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    did: DidValue | None = None
    name: str | None = None
    casualties: ExtractionCasualties | None = None
    vehicles: ExtractionVehicleDetails | None = None


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
