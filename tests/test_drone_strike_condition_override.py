from app.news.services.matching.condition_evidence_override import (
    apply_condition_evidence_override,
)


def test_drone_targeting_is_strike_not_drone_failure() -> None:
    text = "استهداف بطائرة مسيّرة لسيارة مدنية في بلدة رميش"
    assert apply_condition_evidence_override(text, "Drone Failure") == "Bombs"
