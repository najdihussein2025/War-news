from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.ollama_client import JsonObject, OllamaChatClient, OllamaChatMessage
from app.llm.dtos import (
    ExtractionCasualties,
    ExtractionCategory,
    ExtractionCategoryKey,
    ExtractionResult,
)
from app.llm.interfaces import ExtractionClassifierInterface
from app.llm.services.ollama_category_detail_service import OllamaCategoryDetailService
from app.llm.services.ollama_presence_gate_service import (
    LOW_TEMPERATURE,
    OllamaPresenceGateService,
)
from app.llm.services.ollama_relevance_classifier_service import is_valid_reason_text

logger = logging.getLogger(__name__)

ALLOWED_EXTRACTION_CATEGORY_KEYS = frozenset(
    category.value for category in ExtractionCategoryKey
)

GENERAL_EXTRACTION_PROMPT = """أنت مساعد لاستخراج الحقول العامة فقط من خبر عربي واحد عن حادث أمني أو عسكري في لبنان.

مهمتك الوحيدة: استخرج is_relevant و village و action_description و casualties العامة فقط. لا تستخرج categories ولا تحكم على أي فئة في هذه المرحلة.

قواعد الإخراج الصارمة:
- أرجع كائن JSON واحداً صالحاً فقط.
- لا تكتب أي نص قبل JSON أو بعده.
- لا تستخدم Markdown ولا أسوار كود.
- لا تضف أي حقول خارج schema أدناه.
- لا تخمّن ولا تقدّر ولا تفترض ولا تستنتج أي رقم غير مذكور حرفياً وصراحة في النص الأصلي.
- كل القيم النصية مثل أسماء الأماكن أو وصف الحدث يجب أن تكون بالعربية كما وردت أو كما تلخص النص العربي. لا تستخدم أي لغة أخرى.

اقرأ النص فقط، ولا تستخدم أي معرفة خارجية. إذا لم يكن النص عن حادث أمني أو عسكري في لبنان، أرجع is_relevant false واجعل باقي القيم null أو {}.

إذا كان النص ذا صلة:
- village: مصفوفة من أسماء البلدات أو الأماكن المذكورة في الخبر. إذا ورد اسم مكان واحد أرجع مصفوفة بعنصر واحد. إذا وردت أسماء أماكن متعددة أرجعها جميعاً في المصفوفة. إذا لم يظهر أي اسم مكان في النص أرجع null. لا تُرجع سلسلة نصية واحدة بل دائماً مصفوفة أو null.
- action_description: وصف نوع العمل أو الحادث من النص فقط.
- casualties: أعداد الضحايا العامة غير المنسوبة إلى فئة محددة، فقط إذا ذُكرت حرفياً.

قواعد الأعداد:
- استخرج الرقم فقط عندما يكون مكتوباً بشكل مباشر في النص.
- لا تستنتج العدد من صياغة عامة مثل "ضحايا" أو "إصابات" أو "شهداء" إذا لم يوجد رقم صريح.
- لا تحوّل الجمع إلى رقم.
- لا تملأ أي رقم اعتماداً على معرفة خارجية أو افتراضات.

Schema الإخراج الوحيد المسموح:
{
  "is_relevant": true,
  "village": null,
  "action_description": null,
  "casualties": {
    "total_deaths": null,
    "total_injuries": null,
    "deaths": null,
    "injuries": null,
    "male_deaths": null,
    "male_injuries": null,
    "female_deaths": null,
    "female_injuries": null,
    "children_deaths": null,
    "children_injuries": null
  }
}

لا تضف categories في هذا الإخراج."""

GENERAL_EXTRACTION_RESPONSE_SCHEMA: JsonObject = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "is_relevant": {"type": "boolean"},
        "village": {"type": ["array", "null"], "items": {"type": "string"}},
        "action_description": {"type": ["string", "null"]},
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
    },
    "required": ["is_relevant", "village", "action_description", "casualties"],
}


class _RawExtractionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    is_relevant: bool = True
    # Accept both old single-string responses and new array responses.
    village: list[str] | str | None = None
    action_description: str | None = None
    casualties: ExtractionCasualties = Field(default_factory=ExtractionCasualties)


class OllamaExtractionService(ExtractionClassifierInterface):
    def __init__(
        self,
        client: OllamaChatClient,
        presence_gate: OllamaPresenceGateService | None = None,
        category_detail: OllamaCategoryDetailService | None = None,
    ) -> None:
        self.client = client
        self.presence_gate = presence_gate or OllamaPresenceGateService(client)
        self.category_detail = category_detail or OllamaCategoryDetailService(client)

    def extract_tier1(
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
        categories: dict[ExtractionCategoryKey, ExtractionCategory] = {}
        self._inject_casualty_demographics_from_root(
            categories,
            general_response.casualties,
        )

        return ExtractionResult(
            is_relevant=general_response.is_relevant,
            village=self._validated_village_list(
                general_response.village,
                raw_message_id=raw_message_id,
            ),
            action_description=self._validated_text(
                general_response.action_description,
                field_name="action_description",
                raw_message_id=raw_message_id,
            ),
            categories=categories,
            casualties=general_response.casualties,
            presence_category_keys=list(categories_present),
            extraction_tier=1,
            model=self.client.model,
            extracted_at=datetime.now(timezone.utc),
        )

    def extract_tier2_details(
        self,
        post_text: str,
        presence_category_keys: list[ExtractionCategoryKey],
        *,
        root_casualties: ExtractionCasualties | None = None,
        raw_message_id: int | None = None,
    ) -> dict[ExtractionCategoryKey, ExtractionCategory]:
        """Run per-category detail LLM calls for keys detected in Tier 1."""
        category_details: dict[str, ExtractionCategory] = {}
        for category_key in presence_category_keys:
            try:
                category_detail = self.category_detail.extract_detail(
                    post_text,
                    category_key=category_key,
                    raw_message_id=raw_message_id,
                )
            except Exception:
                logger.exception(
                    "Failed to extract category detail category=%s raw_message_id=%s",
                    category_key.value,
                    raw_message_id,
                )
                continue

            if self._is_empty_category_detail(category_detail):
                logger.warning(
                    "Dropped empty category detail category=%s raw_message_id=%s",
                    category_key.value,
                    raw_message_id,
                )
                continue

            category_details[category_key.value] = category_detail

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
        for category_key in categories_present:
            try:
                category_detail = self.category_detail.extract_detail(
                    post_text,
                    category_key=category_key,
                    raw_message_id=raw_message_id,
                )
            except Exception:
                logger.exception(
                    "Failed to extract category detail category=%s raw_message_id=%s",
                    category_key.value,
                    raw_message_id,
                )
                continue

            if self._is_empty_category_detail(category_detail):
                logger.warning(
                    "Dropped empty category detail category=%s raw_message_id=%s",
                    category_key.value,
                    raw_message_id,
                )
                continue

            category_details[category_key.value] = category_detail
        categories = self._validated_categories(
            category_details,
            raw_message_id=raw_message_id,
        )
        self._inject_casualty_demographics_from_root(
            categories,
            general_response.casualties,
        )

        return ExtractionResult(
            is_relevant=general_response.is_relevant,
            village=self._validated_village_list(
                general_response.village,
                raw_message_id=raw_message_id,
            ),
            action_description=self._validated_text(
                general_response.action_description,
                field_name="action_description",
                raw_message_id=raw_message_id,
            ),
            categories=categories,
            casualties=general_response.casualties,
            presence_category_keys=list(categories_present),
            extraction_tier=2,
            model=self.client.model,
            extracted_at=datetime.now(timezone.utc),
        )

    def _extract_general_fields(
        self,
        post_text: str,
        raw_message_id: int | None,
    ) -> _RawExtractionResponse:
        content = self.client.chat(
            [
                OllamaChatMessage(role="system", content=GENERAL_EXTRACTION_PROMPT),
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
