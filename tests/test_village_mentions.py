from app.news.services.matching.village_mentions import find_village_mentions


def _names(text: str) -> list[str]:
    return [item.text for item in find_village_mentions(text)]


def test_scans_real_clause_locations() -> None:
    assert _names("قذائف فوسفورية تجاه أطراف بلدة زوطر الشرقية - قصف مدفعي استهدف الجرمق") == ["زوطر الشرقية", "الجرمق"]
    assert _names("دبابة ميركافا تستهدف وطى الخيام") == ["الخيام"]
    assert _names("قصف مدفعي فوسفوري استهدف اطراف بلدة زوطر الشرقية و قصف مدفعي استهدف المنصوري") == ["زوطر الشرقية", "المنصوري"]


def test_scanner_strips_attached_particle_and_rejects_non_places() -> None:
    assert _names("بالخيام تمشيط") == ["الخيام"]
    assert find_village_mentions("لا توجد أي بلدة في هذا النص") == []


def test_same_name_collision_is_not_silently_selected() -> None:
    hit = next(item for item in find_village_mentions("العين") if item.text == "العين")
    assert hit.ambiguous is True
    assert len(hit.acs_codes) > 1
