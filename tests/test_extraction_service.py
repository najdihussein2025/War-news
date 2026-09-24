from __future__ import annotations

import json
import logging

import httpx
import pytest

from app.core.ollama_client import OllamaChatClient
from app.llm.dtos import (
    DidValue,
    ExtractionCasualties,
    ExtractionCategory,
    ExtractionCategoryKey,
    ExtractionVehicleDetails,
    VillageRoleEntry,
)
from app.llm.services.ollama_extraction_service import (
    MULTI_VILLAGE_NO_SUBEVENTS_REVIEW_REASON,
    OllamaExtractionService,
)
from app.llm.services.ollama_presence_gate_service import OllamaPresenceGateService


class _PresenceGateStub:
    def __init__(self, categories: list[ExtractionCategoryKey]) -> None:
        self.categories = categories
        self.calls = 0

    def categories_present(
        self,
        post_text: str,
        raw_message_id: int | None = None,
    ) -> list[ExtractionCategoryKey]:
        self.calls += 1
        return self.categories


class _CategoryDetailStub:
    def __init__(
        self,
        details: dict[ExtractionCategoryKey, ExtractionCategory],
    ) -> None:
        self.details = details
        self.calls: list[ExtractionCategoryKey] = []

    def extract_detail(
        self,
        post_text: str,
        category_key: ExtractionCategoryKey,
        raw_message_id: int | None = None,
    ) -> ExtractionCategory:
        self.calls.append(category_key)
        return self.details[category_key]


def _client_for_model_contents(contents: list[str]) -> OllamaChatClient:
    remaining_contents = contents.copy()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        return httpx.Response(
            status_code=200,
            json={"message": {"content": remaining_contents.pop(0)}},
        )

    return OllamaChatClient(
        base_url="http://ollama.test",
        api_key=None,
        model="qwen2.5:7b",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )


_GENERAL_RESPONSE_DEFAULT = ["بنت جبيل"]
_SAMPLE_POST_TEXT = "1 جريح في بنت جبيل"
_UNSET = object()


def _general_response(*, village_value: object = _UNSET) -> str:
    if village_value is _UNSET:
        village_value = _GENERAL_RESPONSE_DEFAULT
    return json.dumps(
        {
            "is_relevant": True,
            "village": village_value,
            "action_description": "غارة على المدينة",
            "casualties": {"injuries": 1},
            "casualty_evidence": [
                {"field": "injuries", "evidence_span": "1 جريح"},
            ],
            "casualty_transitions": [],
        },
        ensure_ascii=False,
    )


def test_extract_tier1_skips_category_detail_calls() -> None:
    presence_gate = _PresenceGateStub(categories=[ExtractionCategoryKey.hospital])
    category_detail = _CategoryDetailStub(details={})
    service = OllamaExtractionService(
        client=_client_for_model_contents([_general_response()]),
        presence_gate=presence_gate,
        category_detail=category_detail,
    )

    result = service.extract_tier1(_SAMPLE_POST_TEXT, raw_message_id=42)

    assert presence_gate.calls == 1
    assert category_detail.calls == []
    assert result.extraction_tier == 1
    assert result.presence_category_keys == [ExtractionCategoryKey.hospital]
    assert ExtractionCategoryKey.hospital not in result.categories
    assert ExtractionCategoryKey.casualty_demographics in result.categories


def test_tier1_recovers_both_dash_joined_route_villages() -> None:
    post_text = (
        "الطيران المسير المعادي استهدف دراجة نارية على طريق عام مرج حاروف - زبدين"
    )
    model_response = json.dumps(
        {
            "categories_present": ["vehicles"],
            "category_evidence": [
                {
                    "category_key": "vehicles",
                    "evidence_span": "استهدف دراجة نارية",
                }
            ],
            "is_relevant": True,
            # Reproduce the observed inference miss: only the second endpoint.
            "village": ["زبدين"],
            "village_roles": [
                {
                    "village": "زبدين",
                    "role": "target",
                    "deaths": None,
                    "injuries": None,
                    "evidence_span": None,
                }
            ],
            "action_description": "استهداف دراجة نارية",
            "casualties": {},
            "casualty_transitions": [],
            "casualty_evidence": [],
            "casualty_scope": "unspecified",
            "casualty_scope_evidence": None,
        },
        ensure_ascii=False,
    )
    service = OllamaExtractionService(
        client=_client_for_model_contents([model_response])
    )

    result = service._extract_tier1_combined(post_text, raw_message_id=8788)

    assert set(result.village or []) == {"حاروف", "زبدين"}
    assert {entry.village for entry in result.village_roles} == {
        "حاروف",
        "زبدين",
    }
    assert all(entry.role.value == "target" for entry in result.village_roles)


@pytest.mark.parametrize(
    ("post_text", "model_villages", "expected_target", "expected_qualifier"),
    [
        (
            "قصف في مزرعة حلتا – كفرشوبا.",
            ["حلتا", "كفرشوبا"],
            "مزرعة حلتا",
            "كفرشوبا",
        ),
        (
            "غارة على مزرعة الحمرا - زوطر وتلة علي الطاهر.",
            ["الحمرا", "زوطر", "تلة علي الطاهر"],
            "مزرعة الحمرا",
            "زوطر وتلة علي الطاهر",
        ),
        (
            "غارة على بلدة المنصوري - حي غزاله.",
            ["المنصوري", "حي غزاله"],
            "المنصوري",
            "حي غزاله",
        ),
        (
            "غارة على بلدة كفررمان - النبطية.",
            ["كفررمان", "النبطية"],
            "كفررمان",
            "النبطية",
        ),
        (
            "غارة على بلدة الرمادية - قضاء صور.",
            ["الرمادية", "صور"],
            "الرمادية",
            "قضاء صور",
        ),
        (
            "غارة على بلدة المنصوري - بيوت السياد.",
            ["المنصوري", "بيوت السياد"],
            "المنصوري",
            "بيوت السياد",
        ),
    ],
)
def test_non_route_dash_phrases_collapse_to_target_and_qualifier(
    post_text: str,
    model_villages: list[str],
    expected_target: str,
    expected_qualifier: str,
) -> None:
    villages, roles = OllamaExtractionService._apply_dash_compound_location_rules(
        post_text,
        model_villages,
        [VillageRoleEntry(village=name) for name in model_villages],
    )

    assert villages == [expected_target]
    assert [entry.village for entry in roles] == [expected_target]
    assert roles[0].qualifier_text == expected_qualifier


def test_between_route_phrase_keeps_both_endpoints() -> None:
    villages, roles = OllamaExtractionService._apply_dash_compound_location_rules(
        "غارة على طريق بين كفرتبنيت وزوطر الشرقية.",
        ["كفرتبنيت"],
        [VillageRoleEntry(village="كفرتبنيت")],
    )

    assert villages == ["كفرتبنيت", "زوطر الشرقية"]
    assert [entry.village for entry in roles] == ["كفرتبنيت", "زوطر الشرقية"]


def test_missing_balda_village_is_recovered_when_model_returns_null() -> None:
    """ACCSTUDY-001: model returned village=null despite «بلدة دبل»."""
    post_text = (
        "استهداف بطائرة مسيرة إسرائيلية لسيارة في بلدة دبل. "
        "أسفر الاستهداف عن استشهاد 1 أشخاص وإصابة 1 آخرين بجروح متفاوتة."
    )
    villages, roles = OllamaExtractionService._apply_dash_compound_location_rules(
        post_text,
        None,
        [],
    )

    assert villages == ["دبل"]
    assert [entry.village for entry in roles] == ["دبل"]
    assert roles[0].role.value == "target"


def test_missing_balda_jibbayn_is_recovered_when_model_returns_null() -> None:
    post_text = (
        "غارة جوية إسرائيلية استهدفت منزلاً في بلدة الجبين. "
        "أسفر الاستهداف عن استشهاد 1 أشخاص دون تسجيل إصابات إضافية."
    )
    villages, roles = OllamaExtractionService._apply_dash_compound_location_rules(
        post_text,
        None,
        [],
    )

    assert villages == ["الجبين"]
    assert [entry.village for entry in roles] == ["الجبين"]


def test_fuzzy_area_phrase_collapses_to_first_village_with_alternate() -> None:
    villages, roles, alternatives, evidence = (
        OllamaExtractionService._collapse_fuzzy_area_locations(
            "القوات الإسرائيلية أحرقت حقول الزيتون وبساتين الحمضيات في محيط مجدل زون وبيوت السياد بإطلاق قنابل فوسفورية",
            ["مجدل زون", "بيوت السياد"],
            [],
        )
    )

    assert villages == ["مجدل زون"]
    assert [entry.village for entry in roles] == ["مجدل زون"]
    assert alternatives == ["بيوت السياد"]
    assert "محيط مجدل زون وبيوت السياد" in (evidence or "")


def test_kama_tal_qasf_connector_recovers_dropped_second_target() -> None:
    """Recon bulletin (Zaoutar Ech-Charqiye, 2026-09-20 09:49): the model
    extracted only زوطر الشرقية and silently dropped عيتا الجبل, introduced
    by the distinct-event connector "كما طال القصف". This is the inverse of
    the fuzzy-area محيط bug — two genuinely separate strikes must both
    survive as targets.
    """
    post_text = (
        "طالت الغارات أطراف بلدة زوطر الشرقية في اتجاه ميفدون... "
        "كما طال القصف حرج بلدة عيتا الجبل في قضاء بنت جبيل"
    )
    villages, roles = OllamaExtractionService._apply_dash_compound_location_rules(
        post_text,
        ["زوطر الشرقية"],
        [VillageRoleEntry(village="زوطر الشرقية")],
    )

    assert villages == ["زوطر الشرقية", "عيتا الجبل"]
    assert {entry.village for entry in roles} == {"زوطر الشرقية", "عيتا الجبل"}


def test_kama_tal_qasf_connector_does_not_duplicate_already_extracted_village() -> (
    None
):
    post_text = "كما طال القصف حرج بلدة عيتا الجبل في قضاء بنت جبيل"
    villages, roles = OllamaExtractionService._apply_dash_compound_location_rules(
        post_text,
        ["زوطر الشرقية", "عيتا الجبل"],
        [
            VillageRoleEntry(village="زوطر الشرقية"),
            VillageRoleEntry(village="عيتا الجبل"),
        ],
    )

    assert villages == ["زوطر الشرقية", "عيتا الجبل"]
    assert len(roles) == 2


def test_kama_ghara_ukhra_connector_recovers_accstudy_multi_event_villages() -> None:
    """ACCSTUDY-002: connector-led clauses with separate tolls."""
    post_text = (
        "قصف بالقذائف المدفعية على محيط البلدة في بلدة شبعا، أدى الاستهداف إلى "
        "إصابة 3 أشخاص دون تسجيل حالات وفاة. كما غارة أخرى في بلدة عيناتا، أدى "
        "الاستهداف إلى إصابة 3 أشخاص دون تسجيل حالات وفاة. كما غارة أخرى في "
        "بلدة طيرحرفا، أسفر الاستهداف عن استشهاد 2 أشخاص وإصابة 1 آخرين بجروح متفاوتة."
    )
    villages, roles = OllamaExtractionService._apply_dash_compound_location_rules(
        post_text,
        ["شبعا"],
        [VillageRoleEntry(village="شبعا")],
    )

    assert set(villages or []) == {"شبعا", "عيناتا", "طيرحرفا"}
    assert {entry.village for entry in roles} == {"شبعا", "عيناتا", "طيرحرفا"}


def test_baldat_list_recovers_all_bulletin_aggregate_villages() -> None:
    """ACCSTUDY-003: shared-toll bulletin naming many بلدات."""
    post_text = (
        "شنت طائرات العدو الإسرائيلي سلسلة غارات متزامنة طالت بلدات حولا، "
        "مارون الراس، شبعا، دير ميماس، كفررمان، الشقيف، الخردلي ويارون، ما أسفر "
        "عن سقوط 3 شهداء و8 جرحى في حصيلة إجمالية للغارات."
    )
    villages, roles = OllamaExtractionService._apply_dash_compound_location_rules(
        post_text,
        ["حولا"],
        [VillageRoleEntry(village="حولا")],
    )

    expected = {
        "حولا",
        "مارون الراس",
        "شبعا",
        "دير ميماس",
        "كفررمان",
        "الشقيف",
        "الخردلي",
        "يارون",
    }
    assert set(villages or []) == expected
    assert {entry.village for entry in roles} == expected


def test_kama_tal_qasf_connector_coexists_with_fuzzy_area_collapse() -> None:
    """The محيط collapse and the كما طال القصف recovery must not undo each
    other when a bulletin happens to contain both patterns.
    """
    post_text = (
        "القوات الإسرائيلية أحرقت حقول الزيتون في محيط مجدل زون وبيوت السياد. "
        "كما طال القصف حرج بلدة عيتا الجبل في قضاء بنت جبيل"
    )
    villages, roles = OllamaExtractionService._apply_dash_compound_location_rules(
        post_text,
        ["مجدل زون", "بيوت السياد"],
        [
            VillageRoleEntry(village="مجدل زون"),
            VillageRoleEntry(village="بيوت السياد"),
        ],
    )
    villages, roles, alternatives, _evidence = (
        OllamaExtractionService._collapse_fuzzy_area_locations(
            post_text,
            villages,
            roles,
        )
    )

    assert set(villages) == {"مجدل زون", "عيتا الجبل"}
    assert alternatives == ["بيوت السياد"]


def test_plain_between_phrase_collapses_without_route() -> None:
    villages, roles, alternatives, _evidence = (
        OllamaExtractionService._collapse_fuzzy_area_locations(
            "قصف بين كفرتبنيت وزوطر الشرقية.",
            ["كفرتبنيت", "زوطر الشرقية"],
            [],
        )
    )

    assert villages == ["كفرتبنيت"]
    assert [entry.village for entry in roles] == ["كفرتبنيت"]
    assert alternatives == ["زوطر الشرقية"]


def test_extract_tier1_backstops_per_village_casualties() -> None:
    post_text = (
        "الرمادية قضاء صور: شهيد و15 جريحا\n"
        "كفرمان قضاء النبطية: شهيدان\n"
        "النبطية الفوقا: 3 جرحى من بينهم سيدة\n"
        "ميفدون قضاء النبطية: 4 جرحى\n"
        "عين التينة: جريح سوري الجنسية"
    )
    villages = [
        ("الرمادية", 1, 15, "الرمادية قضاء صور: شهيد و15 جريحا"),
        ("كفرمان", 2, None, "كفرمان قضاء النبطية: شهيدان"),
        ("النبطية الفوقا", None, 3, "النبطية الفوقا: 3 جرحى من بينهم سيدة"),
        ("ميفدون", None, 4, "ميفدون قضاء النبطية: 4 جرحى"),
        ("عين التينة", None, 1, "عين التينة: جريح سوري الجنسية"),
    ]
    response = json.dumps(
        {
            "is_relevant": True,
            "village": [item[0] for item in villages],
            "village_roles": [
                {
                    "village": village,
                    "role": "target",
                    "deaths": deaths,
                    "injuries": injuries,
                    "evidence_span": evidence_span,
                }
                for village, deaths, injuries, evidence_span in villages
            ],
            "action_description": "غارات",
            "casualties": {"deaths": 3, "injuries": 23},
            "casualty_evidence": [
                {"field": "deaths", "evidence_span": "شهيد"},
                {"field": "injuries", "evidence_span": "15 جريحا"},
            ],
            "casualty_transitions": [],
        },
        ensure_ascii=False,
    )
    service = OllamaExtractionService(
        client=_client_for_model_contents([response]),
        presence_gate=_PresenceGateStub(categories=[]),
    )

    result = service.extract_tier1(post_text)

    assert [
        (entry.village, entry.deaths, entry.injuries) for entry in result.village_roles
    ] == [
        ("الرمادية", 1, 15),
        ("كفرمان", 2, None),
        ("النبطية الفوقا", None, 3),
        ("ميفدون", None, 4),
        ("عين التينة", None, 1),
    ]


def test_orchestration_skips_category_detail_when_presence_gate_is_empty() -> None:
    presence_gate = _PresenceGateStub(categories=[])
    category_detail = _CategoryDetailStub(details={})
    service = OllamaExtractionService(
        client=_client_for_model_contents([_general_response()]),
        presence_gate=presence_gate,
        category_detail=category_detail,
    )

    result = service.extract(_SAMPLE_POST_TEXT, raw_message_id=42)

    assert presence_gate.calls == 1
    assert category_detail.calls == []
    assert result.village == ["بنت جبيل"]
    assert result.categories == {
        ExtractionCategoryKey.casualty_demographics: ExtractionCategory(
            did=None,
            name=None,
            casualties=ExtractionCasualties(injuries=1),
        )
    }
    assert result.casualty_evidence[0].field == "injuries"


def test_orchestration_extracts_detail_once_per_present_category() -> None:
    presence_gate = _PresenceGateStub(
        categories=[
            ExtractionCategoryKey.health_center,
            ExtractionCategoryKey.vehicles,
        ]
    )
    category_detail = _CategoryDetailStub(
        details={
            ExtractionCategoryKey.health_center: ExtractionCategory(
                did=DidValue.direct,
                name="مركز صحي",
                casualties=None,
            ),
            ExtractionCategoryKey.vehicles: ExtractionCategory(
                did=DidValue.direct,
                name="سيارة",
                casualties=ExtractionCasualties(injuries=1),
                vehicles=ExtractionVehicleDetails(moto=True),
            ),
        }
    )
    service = OllamaExtractionService(
        client=_client_for_model_contents([_general_response()]),
        presence_gate=presence_gate,
        category_detail=category_detail,
    )

    result = service.extract(_SAMPLE_POST_TEXT, raw_message_id=42)

    assert category_detail.calls == [
        ExtractionCategoryKey.health_center,
        ExtractionCategoryKey.vehicles,
    ]
    assert len(result.categories) == 3
    assert ExtractionCategoryKey.casualty_demographics in result.categories
    assert result.categories[ExtractionCategoryKey.health_center].name == "مركز صحي"
    assert result.categories[ExtractionCategoryKey.vehicles].casualties == (
        ExtractionCasualties(injuries=1)
    )
    assert result.categories[ExtractionCategoryKey.vehicles].vehicles == (
        ExtractionVehicleDetails(moto=True)
    )


def test_presence_gate_drops_invalid_category_key_and_logs(caplog) -> None:
    service = OllamaPresenceGateService(
        _client_for_model_contents(
            [
                json.dumps(
                    {
                        "categories_present": [
                            "vehicles",
                            "attack",
                            "unifil",
                            "vehicles",
                        ],
                        "category_evidence": [
                            {
                                "category_key": "vehicles",
                                "evidence_span": "استهدفت سيارة على الطريق",
                            },
                            {
                                "category_key": "unifil",
                                "evidence_span": "UNIFIL patrol was targeted",
                            },
                        ],
                    }
                )
            ]
        )
    )

    with caplog.at_level(logging.WARNING):
        result = service.categories_present("sample text", raw_message_id=42)

    assert result == [
        ExtractionCategoryKey.vehicles,
        ExtractionCategoryKey.unifil,
    ]
    assert any(
        "Dropped invalid extraction category" in record.message
        and "raw_message_id=42" in record.message
        and "attack" in record.message
        for record in caplog.records
    )


def test_orchestration_isolates_malformed_category_detail(caplog) -> None:
    client = _client_for_model_contents(
        [
            _general_response(),
            "{malformed json",
            json.dumps(
                {
                    "did": "D",
                    "name": "سيارة",
                    "casualties": {"injuries": 1},
                    "casualty_evidence": [
                        {"field": "injuries", "evidence_span": "1 جريح"},
                    ],
                },
                ensure_ascii=False,
            ),
        ]
    )
    presence_gate = _PresenceGateStub(
        categories=[
            ExtractionCategoryKey.health_center,
            ExtractionCategoryKey.vehicles,
        ]
    )
    service = OllamaExtractionService(
        client=client,
        presence_gate=presence_gate,
    )

    with caplog.at_level(logging.ERROR):
        result = service.extract(_SAMPLE_POST_TEXT, raw_message_id=42)

    assert set(result.categories) == {
        ExtractionCategoryKey.vehicles,
        ExtractionCategoryKey.casualty_demographics,
    }
    assert any(
        "Failed to extract category detail category=health_center raw_message_id=42"
        in record.message
        for record in caplog.records
    )


# ---------------------------------------------------------------------------
# Task-4: multi-village extraction tests
# ---------------------------------------------------------------------------


def test_comma_separated_village_string_is_parsed_into_list() -> None:
    """Model returns old-style comma-separated string → normalised to list."""
    presence_gate = _PresenceGateStub(categories=[])
    category_detail = _CategoryDetailStub(details={})
    service = OllamaExtractionService(
        client=_client_for_model_contents(
            [_general_response(village_value="كفرتبنيت, حرش عيتا الجبل")]
        ),
        presence_gate=presence_gate,
        category_detail=category_detail,
    )

    result = service.extract(_SAMPLE_POST_TEXT, raw_message_id=99)

    assert result.village == ["كفرتبنيت", "حرش عيتا الجبل"]


def test_json_array_village_is_used_as_is() -> None:
    """Model returns a JSON array of village names → used directly."""
    presence_gate = _PresenceGateStub(categories=[])
    category_detail = _CategoryDetailStub(details={})
    service = OllamaExtractionService(
        client=_client_for_model_contents(
            [_general_response(village_value=["بنت جبيل", "عيترون"])]
        ),
        presence_gate=presence_gate,
        category_detail=category_detail,
    )

    result = service.extract(_SAMPLE_POST_TEXT, raw_message_id=99)

    assert result.village == ["بنت جبيل", "عيترون"]


def test_null_village_from_model_is_preserved_as_none() -> None:
    """Model returns null → village is None."""
    presence_gate = _PresenceGateStub(categories=[])
    category_detail = _CategoryDetailStub(details={})
    service = OllamaExtractionService(
        client=_client_for_model_contents([_general_response(village_value=None)]),
        presence_gate=presence_gate,
        category_detail=category_detail,
    )

    result = service.extract(_SAMPLE_POST_TEXT, raw_message_id=99)

    assert result.village is None


def test_extract_tier1_parses_sub_events() -> None:
    payload = json.dumps(
        {
            "is_relevant": True,
            "village": ["كفر رمان"],
            "action_description": "غارات على منزل وسيارة",
            "sub_events": [
                {
                    "locations": [
                        {
                            "village": "كفررمان",
                            "role": "target",
                            "deaths": 8,
                            "injuries": 11,
                            "evidence_span": "8 شهداء و11 جريحاً",
                            "qualifier_text": None,
                        }
                    ],
                    "action_text": "غارة على منزل",
                    "casualties": {
                        "deaths": 8,
                        "injuries": 11,
                        "total_deaths": 8,
                        "total_injuries": 11,
                    },
                    "evidence_span": "غارة على منزل في كفررمان أدت إلى 8 شهداء و11 جريحاً",
                    "casualty_evidence": [
                        {"field": "deaths", "evidence_span": "8 شهداء"},
                        {"field": "injuries", "evidence_span": "11 جريحاً"},
                        {"field": "total_deaths", "evidence_span": "8 شهداء"},
                        {"field": "total_injuries", "evidence_span": "11 جريحاً"},
                    ],
                },
                {
                    "locations": [
                        {
                            "village": "كفررمان",
                            "role": "target",
                            "deaths": 1,
                            "injuries": 2,
                            "evidence_span": "فسقط 1 شهيد وأصيب 2",
                            "qualifier_text": None,
                        }
                    ],
                    "action_text": "استهداف سيارة",
                    "casualties": {
                        "deaths": 1,
                        "injuries": 2,
                        "total_deaths": 1,
                        "total_injuries": 2,
                        "male_deaths": 1,
                    },
                    "evidence_span": "استُهدفت سيارة فسقط 1 شهيد وأصيب 2",
                    "casualty_evidence": [
                        {"field": "deaths", "evidence_span": "1 شهيد"},
                        {"field": "injuries", "evidence_span": "أصيب 2"},
                        {"field": "total_deaths", "evidence_span": "1 شهيد"},
                        {"field": "total_injuries", "evidence_span": "أصيب 2"},
                        {"field": "male_deaths", "evidence_span": "1 شهيد"},
                    ],
                },
            ],
            "casualties": {},
            "casualty_evidence": [],
            "casualty_transitions": [],
        },
        ensure_ascii=False,
    )
    service = OllamaExtractionService(
        client=_client_for_model_contents([payload]),
        presence_gate=_PresenceGateStub(categories=[]),
        category_detail=_CategoryDetailStub(details={}),
    )

    result = service.extract_tier1(
        "غارة على منزل في كفررمان أدت إلى 8 شهداء و11 جريحاً، "
        "ثم استُهدفت سيارة فسقط 1 شهيد وأصيب 2",
        raw_message_id=7,
    )

    assert len(result.sub_events) == 2
    assert result.sub_events[0].casualties.deaths == 8
    assert result.sub_events[1].casualties.deaths == 1
    assert result.sub_events[1].casualties.male_deaths == 1
    assert result.sub_events[0].evidence_span is not None
    assert result.casualties.deaths is None


def test_extract_tier1_talloussa_beit_yahoun_scopes_actions_to_sub_events() -> None:
    payload = json.dumps(
        {
            "is_relevant": True,
            "village": ["Talloussa", "Beit Yahoun"],
            "village_roles": [
                {
                    "village": "Talloussa",
                    "role": "target",
                    "deaths": None,
                    "injuries": None,
                    "evidence_span": None,
                    "qualifier_text": None,
                },
                {
                    "village": "Beit Yahoun",
                    "role": "target",
                    "deaths": None,
                    "injuries": None,
                    "evidence_span": None,
                    "qualifier_text": None,
                },
            ],
            "action_description": "multiple actions across 2 villages",
            "sub_events": [
                {
                    "locations": [
                        {
                            "village": "Talloussa",
                            "role": "target",
                            "deaths": None,
                            "injuries": None,
                            "evidence_span": "Sweeping operations near Talloussa",
                            "qualifier_text": None,
                        }
                    ],
                    "action_text": "sweeping operations",
                    "casualties": {},
                    "evidence_span": "Sweeping operations near Talloussa",
                    "casualty_evidence": [],
                },
                {
                    "locations": [
                        {
                            "village": "Beit Yahoun",
                            "role": "target",
                            "deaths": None,
                            "injuries": None,
                            "evidence_span": "illumination and incendiary shelling near Beit Yahoun",
                            "qualifier_text": None,
                        }
                    ],
                    "action_text": "illumination and incendiary shelling",
                    "casualties": {},
                    "evidence_span": "illumination and incendiary shelling near Beit Yahoun",
                    "casualty_evidence": [],
                },
            ],
            "casualties": {},
            "casualty_evidence": [],
            "casualty_transitions": [],
        },
        ensure_ascii=False,
    )
    service = OllamaExtractionService(
        client=_client_for_model_contents([payload]),
        presence_gate=_PresenceGateStub(categories=[]),
        category_detail=_CategoryDetailStub(details={}),
    )

    result = service.extract_tier1(
        "Sweeping operations near Talloussa. "
        "Illumination and incendiary shelling near Beit Yahoun.",
        raw_message_id=77,
    )

    assert [event.locations[0].village for event in result.sub_events] == [
        "Talloussa",
        "Beit Yahoun",
    ]
    assert [event.action_text for event in result.sub_events] == [
        "sweeping operations",
        "illumination and incendiary shelling",
    ]
    assert result.needs_review is False


def test_multi_village_multi_action_without_sub_events_needs_review() -> None:
    payload = json.dumps(
        {
            "is_relevant": True,
            "village": ["Talloussa", "Beit Yahoun"],
            "village_roles": [
                {
                    "village": "Talloussa",
                    "role": "target",
                    "deaths": None,
                    "injuries": None,
                    "evidence_span": None,
                    "qualifier_text": None,
                },
                {
                    "village": "Beit Yahoun",
                    "role": "target",
                    "deaths": None,
                    "injuries": None,
                    "evidence_span": None,
                    "qualifier_text": None,
                },
            ],
            "action_description": "sweeping operations",
            "sub_events": [],
            "casualties": {},
            "casualty_evidence": [],
            "casualty_transitions": [],
        },
        ensure_ascii=False,
    )
    service = OllamaExtractionService(
        client=_client_for_model_contents([payload]),
        presence_gate=_PresenceGateStub(categories=[]),
        category_detail=_CategoryDetailStub(details={}),
    )

    result = service.extract_tier1(
        "Sweeping operations near Talloussa. "
        "Illumination and incendiary shelling near Beit Yahoun.",
        raw_message_id=78,
    )

    assert result.needs_review is True
    assert result.review_reason == MULTI_VILLAGE_NO_SUBEVENTS_REVIEW_REASON
