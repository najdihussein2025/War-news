from app.core.text_sanitizer import strip_emoji_and_pictographs


def test_strip_emoji_and_pictographs_removes_emoji_and_variation_selectors() -> None:
    value = "🚨 عاجل ⛔️ Air activity 🔴"

    assert strip_emoji_and_pictographs(value) == " عاجل  Air activity "
