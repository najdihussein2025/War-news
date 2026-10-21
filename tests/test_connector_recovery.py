from app.llm.services.sectioned_bulletin import recover_connector_sub_events


def _pairs(text: str) -> list[tuple[str | None, list[str]]]:
    return [(event.action_text, [location.village for location in event.locations]) for event in recover_connector_sub_events(text)]


def test_recovers_same_village_concurrent_actions() -> None:
    assert _pairs("دبابة ميركافا تستهدف منطقة وطى الخيام تزامناً مع حملة تمشيط بالاسلحة الرشاشة") == [
        ("Tank Fire", ["الخيام"]),
        ("تمشيط بالأسلحة الرشاشة", ["الخيام"]),
    ]


def test_recovers_two_village_actions() -> None:
    assert _pairs("قوات الاحتلال نفذت عملية تفجير كبيرة في بيت ياحون تزامناً مع قصف مدفعي استهدف أطراف برعشيت") == [
        ("تفجير", ["بيت ياحون"]),
        ("قصف مدفعي", ["برعشيت"]),
    ]


def test_does_not_split_non_action_connector() -> None:
    assert recover_connector_sub_events("قصف مدفعي على الخيام تزامناً مع ذكرى وطنية") == []


def test_single_action_is_unchanged() -> None:
    assert recover_connector_sub_events("قصف مدفعي على بلدة الخيام") == []
