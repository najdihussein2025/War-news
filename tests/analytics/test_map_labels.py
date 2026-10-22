from app.analytics.services import map_labels


class Result:
    def mappings(self):
        return iter([
            {"code": "1", "ref_name_en": "Village", "ref_name_ar": "قرية", "coord_x": 750000, "coord_y": 3700000},
            {"code": "2", "ref_name_en": "Missing", "ref_name_ar": "", "coord_x": None, "coord_y": None},
            {"code": None, "ref_name_en": "Unlinked", "ref_name_ar": "", "coord_x": 750000, "coord_y": 3700000},
        ])


class DB:
    def execute(self, statement):
        return Result()


def test_table_coordinates_are_converted_and_missing_labels_reported(monkeypatch):
    monkeypatch.setattr(map_labels, "cached", lambda route, params, build: build())
    payload = map_labels.village_labels(DB())
    assert payload["missing_coordinates"] == 1
    assert payload["unlinked"] == 1
    assert len(payload["features"]) == 1
    point = payload["features"][0]
    lon, lat = point["geometry"]["coordinates"]
    assert 35 < lon < 37 and 33 < lat < 35
    assert point["properties"]["name_ar"] == "قرية"


def test_geometry_cache_has_no_filter_key(monkeypatch):
    calls = []
    monkeypatch.setattr(map_labels, "cached", lambda route, params, build: calls.append((route, params)) or {})
    map_labels.village_labels(DB())
    assert calls == [("village-labels-v1", {})]
