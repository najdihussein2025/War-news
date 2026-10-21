from app.news.services.air_violations.caza_alias_resolver import resolve_caza_alias


def test_resolves_caza_display_aliases() -> None:
    assert resolve_caza_alias("Tyre") == "Sour"
    assert resolve_caza_alias("Nabatieh") == "Nabatiye"
    assert resolve_caza_alias("Marjayoun") == "Marjaayoun"
    assert resolve_caza_alias("Bint Jbeil") == "Bint Jubail"
    assert resolve_caza_alias("West Bekaa") == "West Bekaa"


def test_resolves_sector_aliases() -> None:
    assert resolve_caza_alias("تحليق فوق القطاع الشرقي") == "Marjaayoun"
    assert resolve_caza_alias("تحليق فوق القطاع الغربي") == "Sour"
    assert resolve_caza_alias("تحليق فوق القطاع الأوسط") == "Bint Jubail"


def test_unresolved_caza_alias_returns_none() -> None:
    assert resolve_caza_alias("Not a caza") is None



def test_generic_bekaa_is_not_west_bekaa() -> None:
    # A bare "Bekaa" must not inherit West Bekaa's 6-hour drone window.
    assert resolve_caza_alias("Bekaa") is None
