from __future__ import annotations

import pytest

from app.news.services.clustering.raw_message_embedding_service import strip_boilerplate


def test_strips_nna_attribution_without_removing_content() -> None:
    text = '"الوكالة الوطنية": تحرك للدبابات باتجاه الخيام'

    assert strip_boilerplate(text) == "تحرك للدبابات باتجاه الخيام"


def test_strips_al_mayadeen_correspondent_attribution() -> None:
    text = "لبنان: مراسلة الميادين في الجنوب: قصف مدفعي على أطراف البلدة"

    assert strip_boilerplate(text) == "قصف مدفعي على أطراف البلدة"


def test_strips_lebanon24_prefix_and_trailing_noise() -> None:
    text = "«لبنان 24»: غارة على النبطية #lebanon24 https://lebanon24.com/news"

    assert strip_boilerplate(text) == "غارة على النبطية"


def test_leaves_message_without_boilerplate_unchanged() -> None:
    text = "تحرك للدبابات قرب مرجعيون"

    assert strip_boilerplate(text) == text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "صفحة الإعلامي الشهيد علي شعيب: ● غارة على بلدة الخيام",
            "غارة على بلدة الخيام",
        ),
        (
            "قصف مدفعي على أطراف البلدة T.me/mehwaralmokawma تفاصيل القناة",
            "قصف مدفعي على أطراف البلدة",
        ),
        (
            "غارة على النبطية ───── 📲 قناة بنت جبيل على واتساب رابط القناة",
            "غارة على النبطية",
        ),
    ],
)
def test_preexisting_outlet_patterns_still_strip(
    text: str,
    expected: str,
) -> None:
    assert strip_boilerplate(text) == expected
