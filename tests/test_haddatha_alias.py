"""حداثا transliterated as "Hardinga" must resolve to Haddatha (Bint Jbeil), not Hardine (Batroun)."""
from types import SimpleNamespace

import pytest

from app.news.dtos import MatchResultStatus
from app.news.services.matching.matching_service import MatchingService
from app.news.services.matching.village_aliases import PROPOSED_VILLAGE_LOCATION_ALIASES
from tests.test_matching_service import _extraction, _GeoVillageRepositoryStub, _SimilarRepositoryStub

HADDATHA_ACS = 72231


@pytest.mark.parametrize("mention", [" Hardinga", "Hardinga", "hardinga", "Harding"])
def test_hardinga_resolves_to_haddatha_not_hardine(mention: str) -> None:
    haddatha = SimpleNamespace(id=601, ref_name_ar="حداثا", acs_name="Haddatha", cad_name="Haddatha",
                               caza_ar="بنت جبيل", caza_en="Bint Jubail")
    hardine = SimpleNamespace(id=638, ref_name_ar="حردين", acs_name="Hardine", cad_name="Hardine",
                              caza_ar="البترون", caza_en="Batroun")
    key = mention.strip()
    villages = _GeoVillageRepositoryStub({key: [(hardine, 0.545)]}, aliases={key: haddatha})

    result = MatchingService(villages, _SimilarRepositoryStub(None, None)).match(
        _extraction(village=[mention], action=None)
    )

    vm = result.village_matches[0]
    assert vm.matched_village_id == 601
    assert vm.village_confidence == 1.0
    assert vm.village_match_status == MatchResultStatus.matched
    assert vm.alias_matched is True


def test_catalog_maps_every_latin_spelling_to_haddatha() -> None:
    by_text = {a.alias_text: a.parent_acs_code for a in PROPOSED_VILLAGE_LOCATION_ALIASES}
    for spelling in ("Hardinga", "hardinga", "Harding", "harding"):
        assert by_text[spelling] == HADDATHA_ACS
