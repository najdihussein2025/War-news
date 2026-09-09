from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import settings
from app.core.ollama_client import JsonObject, OllamaChatClient, OllamaChatMessage
from app.llm.dtos import (
    CasualtyCountEvidence,
    CasualtyScope,
    CasualtyTransition,
    ExtractionCasualties,
    ExtractionCategory,
    ExtractionCategoryKey,
    ExtractionResult,
    VillageRoleEntry,
)
from app.llm.interfaces import ExtractionClassifierInterface
from app.llm.services.ollama_category_detail_service import OllamaCategoryDetailService
from app.llm.services.ollama_auth_failures import coerce_ollama_auth_failure
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

ALLOWED_EXTRACTION_CATEGORY_KEYS = frozenset(
    category.value for category in ExtractionCategoryKey
)

GENERAL_EXTRACTION_PROMPT = """أنت مساعد لاستخراج الحقول العامة فقط من خبر عربي واحد عن حادث أمني أو عسكري في لبنان.

مهمتك الوحيدة: استخرج is_relevant و village و village_roles و action_description و casualties العامة فقط. لا تستخرج categories ولا تحكم على أي فئة في هذه المرحلة.

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
- village_roles: مصفوفة من كائنات بالشكل {"village":"اسم البلدة","role":"origin|target","deaths":null,"injuries":null,"evidence_span":null}. استخدم role="origin" فقط لموضع المنصة أو الدبابة أو موقع الإطلاق أو نقطة التمركز، واستخدم role="target" لمكان القصف/الضربة/الضرر الفعلي.
- عند ذكر أكثر من بلدة أو موقع، استخرج في كل عنصر target أعداد deaths وinjuries الخاصة بتلك البلدة من جملتها أو عبارتها فقط، ولا تنسخ الحصيلة الإجمالية للنشرة إلى البلدات. يجب أن يكون evidence_span مقطعاً حرفياً قصيراً يربط اسم البلدة بأرقامها.
- إذا ذُكرت بلدة target بلا عدد صريح خاص بها، اجعل deaths وinjuries وevidence_span لها null، لا 0 ولا حصيلة النشرة. طبّق على كل بلدة قاعدة الألفاظ المبهمة نفسها: عشرات، مئات، عدد من، بضعة وغيرها تعني null ولا تتحول إلى رقم.
- عند ذكر بلدة واحدة فقط، اجعل أرقام عنصر village_roles مطابقة لأرقام casualties العامة إن وُجدت، مع evidence_span حرفي، أو اتركها null. كلاهما مقبول لأن مسار البلدة الواحدة يستخدم casualties العامة.
- action_description: وصف نوع العمل أو الحادث من النص فقط.
- casualties: أعداد الضحايا العامة غير المنسوبة إلى فئة محددة، فقط إذا ذُكرت حرفياً.
- casualty_transitions: انتقالات حالة بين جرحى ووفيات في *متابعات* لنفس الحادث. استخدمها عندما يذكر النص أن جرحى سابقين توفوا أو «بقي X جرحى وتوفي Y» أو «توفى واحد من الجرحى» دون إعادة عدّ كل الجرحى. لا تستخدمها للأخبار الأولية ولا للإضافات البسيطة مثل «5 جرحى جدد».
- قاعدة إلزامية: إذا قال النص صراحة إن مصاباً أو جريحاً سابقاً توفي، فأرجع دائماً [{"from_status":"injured","to_status":"deceased","count":1}] حتى لو ذكر النص أيضاً حصيلة جديدة أو عدداً متبقياً للجرحى.
- يشمل ذلك على الأقل الصيغ: «استشهاد أحد جريحي/الجرحى»، «وفاة أحد المصابين متأثراً بجراحه»، و«فارق أحد الجرحى الحياة».
- قد تأتي عبارة الانتقال وعبارة الحصيلة أو العدد المتبقي في شقين مختلفين من الجملة نفسها أو في جملة طويلة متعددة الفواصل؛ اربطهما كتحديث واحد لنفس الحادث ولا تعتبر الحصيلة خبراً منفصلاً.

أمثلة على casualty_transitions:
1) «توفى أحد الجرحى جراء إصابته» → [{"from_status":"injured","to_status":"deceased","count":1}] و casualties.deaths=1 (اختياري).
2) «بقي 3 جرحى وتوفي واحد» → [{"from_status":"injured","to_status":"deceased","count":1}] — لا حاجة لذكر injuries=3 في casualties.
3) «أعلنت وزارة الصحة وفاة أحد المصابين متأثراً بجراحه» → [{"from_status":"injured","to_status":"deceased","count":1}]
4) «أحد جريحي الانفجار استشهد... لتصبح الحصيلة 3 شهداء وجريح واحد» → [{"from_status":"injured","to_status":"deceased","count":1}] حتى لو جاءت الحصيلة في شق لاحق من الجملة.
5) «أصيب 5 جرحى إضافيين» → casualty_transitions=[] (إضافة فقط، بدون انتقال).

أمثلة على village_roles:
1) «دبابة متمركزة في البياض تقصف المنصوري» → village=["البياض","المنصوري"] و village_roles=[{"village":"البياض","role":"origin","deaths":null,"injuries":null,"evidence_span":null},{"village":"المنصوري","role":"target","deaths":null,"injuries":null,"evidence_span":null}]
2) «غارة على عيتا الشعب أدت إلى 2 جريحين» → village=["عيتا الشعب"] و village_roles=[{"village":"عيتا الشعب","role":"target","deaths":null,"injuries":2,"evidence_span":"عيتا الشعب أدت إلى 2 جريحين"}]
3) «المنصوري: شهيد و3 جرحى؛ مجدل زون: 4 جرحى» → village=["المنصوري","مجدل زون"] و village_roles=[{"village":"المنصوري","role":"target","deaths":1,"injuries":3,"evidence_span":"المنصوري: شهيد و3 جرحى"},{"village":"مجدل زون","role":"target","deaths":null,"injuries":4,"evidence_span":"مجدل زون: 4 جرحى"}]
- عند وجود مكان انطلاق ومكان استهداف، أضف عنصراً origin للأول وعنصراً target للثاني.
- عند وجود مكان استهداف واحد، أضف عنصراً target له.
- عند وجود عدة أماكن مستهدفة، أضف عنصراً target مستقلاً لكل مكان واربط به حصيلته الصريحة وحدها إن وجدت.

قواعد الأعداد:
- استخرج الرقم فقط عندما يكون مكتوباً بشكل مباشر في النص.
- لا تستنتج العدد من صياغة عامة مثل "ضحايا" أو "إصابات" أو "شهداء" إذا لم يوجد رقم صريح.
- لا تحوّل الجمع إلى رقم.
- لا تملأ أي رقم اعتماداً على معرفة خارجية أو افتراضات.
- الألفاظ التالية تدل على عدد غير محدد ويجب ألا تُترجم إلى رقم: عشرات، عشرات الجرحى، عشرات الشهداء، مئات، المئات، عدد من، عدد كبير من، كثير من، العديد من، بضعة، بعض. عند ورود أي من هذه الألفاظ دون رقم صريح مرافق، اترك الحقل فارغاً (null) ولا تفترض رقماً تقريبياً.
- مثال إلزامي: «عشرات الجرحى والشهداء» أو «عشرات جرحى وشهداء» لا تعني 10. اجعل deaths وinjuries وtotal_deaths وtotal_injuries كلها null ما لم يرد رقم صريح لكل حصيلة في النص.
- لا تستنتج عدد الأطفال أو النساء أو أي تصنيف ديموغرافي فرعي من عبارات مثل "بينهم أطفال" أو "بينهم نساء" ما لم يُذكر رقم صريح لتلك الفئة تحديداً في النص. ذِكر وجود فئة دون رقم لا يعني تقدير عدد لها.
- لكل حقل عدد غير null في casualties، أضف عنصراً في casualty_evidence بالشكل {"field":"اسم_الحقل","evidence_span":"المقطع الحرفي من النص الذي يحتوي الرقم الصريح"}. إذا لم يوجد مقطع رقمي صريح لا تملأ الحقل.
- casualty_scope يصف علاقة أرقام الضحايا بالبلدات: استخدم per_village_exact عندما يرتبط رقم صريح ببلدة target واحدة في جملتها أو عبارتها؛ واستخدم bulletin_aggregate عندما تغطي حصيلة واحدة مشتركة بلدتين target أو أكثر بلا تفصيل رقمي لكل بلدة؛ واستخدم unspecified عند غياب الربط أو الأرقام أو الضحايا.
- مع bulletin_aggregate ضع الحصيلة المشتركة في casualties.total_deaths وcasualties.total_injuries واترك casualties.deaths وcasualties.injuries فارغين. مع per_village_exact ضع أرقام كل بلدة في عنصرها ضمن village_roles، ولا تستخدم أرقام root إلا عند وجود بلدة target واحدة.
- casualty_scope_evidence يجب أن يكون الجملة أو العبارة الحرفية الكاملة التي تبرر التصنيف، وأن تتضمن الرقم والسياق الذي يوضح هل يرتبط ببلدة واحدة أم بقائمة بلدات. لا تُرجع عبارة الرقم وحدها. استخدم null مع unspecified أو عند غياب عبارة حرفية كافية.

Schema الإخراج الوحيد المسموح:
{
  "is_relevant": true,
  "village": null,
  "village_roles": [],
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
  },
  "casualty_evidence": [],
  "casualty_scope": "unspecified",
  "casualty_scope_evidence": null,
  "casualty_transitions": []
}

قاعدة ربط الفئات الديموغرافية: عندما تأتي عبارة «من بينهم/من بين الجرحى» بعد عدد الجرحى مباشرة، انسب أعداد الأطفال والنساء والرجال التالية إلى injuries لا إلى deaths. الكلمات «سيدة/سيدات/امرأة/نساء» تعني female ويجب عدم تجاهل رقمها. مثال إلزامي: «4 شهداء و33 جريحا من بينهم 6 أطفال و4 سيدات» يعني deaths=4 وinjuries=33 وchildren_injuries=6 وfemale_injuries=4، مع إبقاء children_deaths وfemale_deaths null.

لا تضف categories في هذا الإخراج."""

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
                },
                "required": [
                    "village",
                    "role",
                    "deaths",
                    "injuries",
                    "evidence_span",
                ],
            },
        },
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
        "casualties",
        "casualty_transitions",
        "casualty_evidence",
        "casualty_scope",
        "casualty_scope_evidence",
    ],
}

COMBINED_TIER1_PROMPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "phase2-extraction-testing"
    / "combined_tier1_presence_extraction_instruction.txt"
)
COMBINED_TIER1_PROMPT = COMBINED_TIER1_PROMPT_PATH.read_text(encoding="utf-8")

COMBINED_TIER1_RESPONSE_SCHEMA: JsonObject = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "categories_present": PRESENCE_GATE_RESPONSE_SCHEMA["properties"]["categories_present"],  # type: ignore[index]
        "category_evidence": PRESENCE_GATE_RESPONSE_SCHEMA["properties"]["category_evidence"],  # type: ignore[index]
        "is_relevant": {"type": "boolean"},
        "village": {"type": ["array", "null"], "items": {"type": "string"}},
        "village_roles": GENERAL_EXTRACTION_RESPONSE_SCHEMA["properties"]["village_roles"],  # type: ignore[index]
        "action_description": {"type": ["string", "null"]},
        "casualties": GENERAL_EXTRACTION_RESPONSE_SCHEMA["properties"]["casualties"],  # type: ignore[index]
        "casualty_transitions": GENERAL_EXTRACTION_RESPONSE_SCHEMA["properties"]["casualty_transitions"],  # type: ignore[index]
        "casualty_evidence": GENERAL_EXTRACTION_RESPONSE_SCHEMA["properties"]["casualty_evidence"],  # type: ignore[index]
        "casualty_scope": GENERAL_EXTRACTION_RESPONSE_SCHEMA["properties"]["casualty_scope"],  # type: ignore[index]
        "casualty_scope_evidence": GENERAL_EXTRACTION_RESPONSE_SCHEMA["properties"]["casualty_scope_evidence"],  # type: ignore[index]
    },
    "required": [
        "categories_present",
        "category_evidence",
        "is_relevant",
        "village",
        "village_roles",
        "action_description",
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
    casualties: ExtractionCasualties = Field(default_factory=ExtractionCasualties)
    casualty_transitions: list[CasualtyTransition] = Field(default_factory=list)
    casualty_evidence: list[CasualtyCountEvidence] = Field(default_factory=list)
    casualty_scope: CasualtyScope = CasualtyScope.unspecified
    casualty_scope_evidence: str | None = None


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
                OllamaChatMessage(role="system", content=COMBINED_TIER1_PROMPT),
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
        scope, scope_evidence, scope_needs_review, scope_reason = (
            self._validated_casualty_scope(
                general_response,
                village_roles=village_roles,
                post_text=post_text,
                raw_message_id=raw_message_id,
            )
        )

        return ExtractionResult(
            is_relevant=general_response.is_relevant,
            village=self._validated_village_list(
                general_response.village,
                raw_message_id=raw_message_id,
            ),
            village_roles=village_roles,
            action_description=self._validated_text(
                general_response.action_description,
                field_name="action_description",
                raw_message_id=raw_message_id,
            ),
            categories=categories,
            casualties=casualties,
            casualty_evidence=casualty_evidence,
            casualty_transitions=list(general_response.casualty_transitions),
            casualty_scope=scope,
            casualty_scope_evidence=scope_evidence,
            casualty_scope_needs_review=scope_needs_review,
            casualty_scope_review_reason=scope_reason,
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
            return {}

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
        categories = self._validated_categories(
            category_details,
            raw_message_id=raw_message_id,
        )
        casualties, casualty_evidence = apply_casualty_count_backstop(
            post_text,
            general_response.casualties,
            list(general_response.casualty_evidence),
            raw_message_id=raw_message_id,
        )
        self._inject_casualty_demographics_from_root(
            categories,
            casualties,
        )
        village_roles = self._validated_village_roles(
            general_response.village_roles,
            post_text=post_text,
            raw_message_id=raw_message_id,
        )
        scope, scope_evidence, scope_needs_review, scope_reason = (
            self._validated_casualty_scope(
                general_response,
                village_roles=village_roles,
                post_text=post_text,
                raw_message_id=raw_message_id,
            )
        )

        return ExtractionResult(
            is_relevant=general_response.is_relevant,
            village=self._validated_village_list(
                general_response.village,
                raw_message_id=raw_message_id,
            ),
            village_roles=village_roles,
            action_description=self._validated_text(
                general_response.action_description,
                field_name="action_description",
                raw_message_id=raw_message_id,
            ),
            categories=categories,
            casualties=casualties,
            casualty_evidence=casualty_evidence,
            casualty_transitions=list(general_response.casualty_transitions),
            casualty_scope=scope,
            casualty_scope_evidence=scope_evidence,
            casualty_scope_needs_review=scope_needs_review,
            casualty_scope_review_reason=scope_reason,
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
