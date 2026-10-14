import json
from pathlib import Path


FIXTURES = Path(__file__).parent / "fixtures" / "casualty_gold"
KFARROUMANE_SNAPSHOTS = (5050, 5052, 5310)


def test_every_gold_fixture_has_a_reviewed_expected_value():
    fixtures = sorted(FIXTURES.glob("*.json"))
    assert fixtures
    assert all(json.loads(path.read_text(encoding="utf-8"))["expected"] is not None for path in fixtures)


def test_kfarroumane_snapshot_expectations_are_assertable():
    values = {
        raw_id: json.loads((FIXTURES / f"{raw_id}.json").read_text(encoding="utf-8"))["expected"]
        for raw_id in KFARROUMANE_SNAPSHOTS
    }
    assert values[5050]["resolver"] == "headline_equals_parts_use_parts"
    assert values[5050]["casualties"] == [{"village": "Kfarroumane", "deaths": 9, "injuries": 13}]
    assert values[5052]["casualties"] == [{"village": "Kfarroumane", "deaths": 8, "injuries": 11}]
    assert values[5310]["casualties"] == [{"village": "Kfarroumane", "deaths": 1, "injuries": None}]
