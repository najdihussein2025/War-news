from app.news.repositories.map_event_repository import _matched_village_id, utm36n_to_wgs84


def test_converts_acs_utm_coordinates_to_lebanon_coordinates() -> None:
    latitude, longitude = utm36n_to_wgs84(750835.01408, 3740954.40849)
    assert 33.0 < latitude < 35.0
    assert 35.0 < longitude < 37.0


def test_extracts_village_id_from_match_result() -> None:
    assert _matched_village_id({"village_matches": [{"matched_village_id": "42"}]}) == 42
    assert _matched_village_id({"matched_village_id": 9}) == 9
    assert _matched_village_id(None) is None
