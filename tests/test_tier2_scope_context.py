from __future__ import annotations

from unittest.mock import MagicMock

from app.llm.dtos import ExtractionCategoryKey
from app.llm.services.ollama_category_detail_service import (
    OllamaCategoryDetailService,
    tier2_scope_context,
)


def test_single_village_gets_no_scope_context() -> None:
    assert tier2_scope_context(["طلوسة"], "unspecified") is None
    assert tier2_scope_context(None, None) is None


def test_multi_village_context_names_villages_and_scope() -> None:
    context = tier2_scope_context(["طلوسة", "بيت ياحون"], "bulletin_aggregate")

    assert "طلوسة" in context and "بيت ياحون" in context
    assert "casualty_scope=bulletin_aggregate" in context
    assert "لا تنسخ الحصيلة الإجمالية" in context


def test_scope_context_reaches_the_tier2_user_prompt() -> None:
    client = MagicMock()
    client.chat.return_value = "{}"
    service = OllamaCategoryDetailService(client)
    service._parse_response = MagicMock()
    context = tier2_scope_context(["طلوسة", "بيت ياحون"], "unspecified")

    service.extract_detail(
        "خبر",
        category_key=ExtractionCategoryKey.lebanese_army,
        scope_context=context,
    )

    user_message = client.chat.call_args.args[0][1].content
    assert user_message.index(context) < user_message.index("النص:")
