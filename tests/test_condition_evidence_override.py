from app.news.services.condition_evidence_override import apply_condition_evidence_override


def test_tank_firing_at_village_overrides_artillery() -> None:
    text = "قصف تنفذه دبابة ميركافا يستهدف أحياء زوطر الشرقية"
    assert apply_condition_evidence_override(text, "Artillery Shelling") == "Tank Fire"


def test_tank_that_targets_village_overrides_artillery() -> None:
    text = "دبابة ميركافا معادية متمركزة في البياضة تستهدف بلدة المنصوري بالقذائف"
    assert apply_condition_evidence_override(text, "Artillery Shelling") == "Tank Fire"


def test_tank_mentioned_as_target_does_not_override() -> None:
    text = "استهدفنا بصاروخ موجه دبابة ميركافا وحققنا إصابة مباشرة"
    assert apply_condition_evidence_override(text, "Bombs") == "Bombs"


def test_tank_incursion_does_not_become_tank_fire() -> None:
    text = "توغل دبابتين ميركافا باتجاه المنطقة مع إطلاق رشقات رشاشة"
    assert apply_condition_evidence_override(text, "Ground Incursion") == "Ground Incursion"


def test_warplane_airstrike_becomes_bombs() -> None:
    text = "الطيران الحربي الإسرائيلي أغار مستهدفًا بلدة المنصوري"
    assert apply_condition_evidence_override(text, "Warplane") == "Bombs"


def test_warplane_overflight_remains_air_activity() -> None:
    text = "تحليق طيران حربي فوق الجنوب"
    assert apply_condition_evidence_override(text, "Warplane") == "Warplane"


def test_warning_and_feigned_raids_keep_specific_conditions() -> None:
    assert apply_condition_evidence_override("غارة تحذيرية", "Bombs") == "Warning Raid"
    assert apply_condition_evidence_override("غارات وهمية", "Bombs") == "Feigned Attacks"
