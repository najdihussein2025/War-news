from app.news.services.matching.condition_evidence_override import (
    apply_condition_evidence_override,
)
import pytest


@pytest.mark.parametrize("weapon", ["قنبلة صوتية", "قنبله صوتيه", "قنابل صوتية"])
def test_sound_bombs_use_specific_condition(weapon: str) -> None:
    text = f"محلقة معادية القت {weapon} على بلدة ياطر"
    assert apply_condition_evidence_override(text, "Bombs") == "Sound Bombs"


def test_drone_targeting_is_strike_not_drone_failure() -> None:
    text = "استهداف بطائرة مسيّرة لسيارة مدنية في بلدة رميش"
    assert apply_condition_evidence_override(text, "Drone Failure") == "Bombs"
