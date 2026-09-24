from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.core.llm_knowledge.loader import (
    PromptBuilder,
    is_multi_village_candidate,
    scan_terminology,
    terms_by_category,
    _load_terminology_file,
    TerminologyEntry,
)


@pytest.fixture
def builder() -> PromptBuilder:
    return PromptBuilder()


def test_scan_terminology_finds_exact_arabic_terms() -> None:
    entries = (
        TerminologyEntry(term="شهيد", category="male_death", meaning="male_death"),
        TerminologyEntry(term="الدفاع المدني", category="org", meaning="civil_defense"),
    )
    matched = scan_terminology("استشهد شهيد وذكر الدفاع المدني", entries)
    terms = {item.term for item in matched}
    assert "شهيد" in terms
    assert "الدفاع المدني" in terms


def test_scan_terminology_uses_normalized_form() -> None:
    entries = (
        TerminologyEntry(
            term="حصيلة أولية",
            category="revision",
            meaning="preliminary_toll",
            normalized="حصيله اوليه",
        ),
    )
    matched = scan_terminology("اعلنت حصيلة أولية بثلاثة شهداء", entries)
    assert len(matched) == 1
    assert matched[0].meaning == "preliminary_toll"


def test_is_multi_village_candidate_dash_route() -> None:
    text = "استهدف دراجة نارية على طريق عام مرج حاروف - زبدين"
    assert is_multi_village_candidate(text) is True


def test_is_multi_village_candidate_fuzzy_area_is_false() -> None:
    assert (
        is_multi_village_candidate("قصف في محيط مجدل زون وبيوت السياد") is False
    )
    assert is_multi_village_candidate("غارة بين كفرتبنيت وزوطر الشرقية") is False


def test_is_multi_village_candidate_between_route_is_true() -> None:
    assert is_multi_village_candidate("غارة على طريق بين كفرتبنيت وزوطر الشرقية") is True


def test_is_multi_village_candidate_kama_ghara_connector() -> None:
    assert (
        is_multi_village_candidate(
            "قصف في بلدة شبعا. كما غارة أخرى في بلدة عيناتا"
        )
        is True
    )


def test_is_multi_village_candidate_baldat_list() -> None:
    assert (
        is_multi_village_candidate(
            "غارات طالت بلدات حولا، مارون الراس، شبعا ويارون"
        )
        is True
    )


def test_is_multi_village_candidate_single_village_false() -> None:
    assert is_multi_village_candidate("غارة على عيتا الشعب") is False


def test_build_loads_core_rules(builder: PromptBuilder) -> None:
    context = builder.build("casualty_scope", "المنصوري: شهيد و3 جرحى")
    assert "casualty_scope" in context.rules or "merge" in context.rules.lower()
    assert context.stage == "casualty_scope"


def test_build_gates_situational_multi_village_rules(builder: PromptBuilder) -> None:
    multi = builder.build(
        "tier1_extraction",
        "المنصوري: شهيد؛ مجدل زون: 4 جرحى",
    )
    single = builder.build("tier1_extraction", "غارة على عيتا الشعب")
    assert "rules/tier1_multi_village.md" in multi.situational_rules_loaded
    assert "rules/tier1_multi_village.md" not in single.situational_rules_loaded


def test_build_retrieves_fewshot_via_embedding() -> None:
    embedding = MagicMock()
    embedding.generate.side_effect = [
        [1.0, 0.0],
        [0.9, 0.1],
        [0.1, 0.9],
        [0.2, 0.8],
    ]
    builder = PromptBuilder(embedding_service=embedding)
    context = builder.build(
        "casualty_scope",
        "المنصوري: شهيد و3 جرحى؛ مجدل زون: 4 جرحى",
    )
    assert len(context.fewshot_examples) <= 5
    assert context.fewshot_examples


def test_missing_terminology_file_returns_empty() -> None:
    missing_root = str(Path(__file__).resolve().parent / "nonexistent_llm_knowledge_root")
    _load_terminology_file.cache_clear()
    result = _load_terminology_file("missing.yaml", missing_root)
    assert result == ()


def test_terms_by_category_loads_role_nouns() -> None:
    male = terms_by_category("terminology/casualty_gender.yaml", "male_role_noun")
    assert "مسعف" in male
    assert "جندي" in male
    female = terms_by_category("terminology/casualty_gender.yaml", "female_role_noun")
    assert "مسعفه" in female


def test_as_prompt_fragment_includes_matched_terminology(builder: PromptBuilder) -> None:
    context = builder.build(
        "presence_gate",
        "انتشال الدفاع المدني للجثث",
    )
    fragment = context.as_prompt_fragment()
    assert "Matched terminology" in fragment or "الدفاع المدني" in fragment
