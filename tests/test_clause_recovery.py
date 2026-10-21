from app.llm.services.clause_recovery import recover_clause_sub_events


def test_clause_recovery_keeps_action_location_pairs_local() -> None:
    events = recover_clause_sub_events("قذائف فوسفورية تجاه أطراف بلدة زوطر الشرقية - قصف مدفعي معاد استهدف الجرمق")
    assert [(event.locations[0].village, event.action_text) for event in events] == [
        ("زوطر الشرقية", "Phosphorus Bombs"), ("الجرمق", "Artillery Shelling")
    ]


def test_clause_recovery_keeps_same_village_concurrent_actions() -> None:
    events = recover_clause_sub_events("دبابة ميركافا تستهدف وطى الخيام تزامناً مع حملة تمشيط بالأسلحة الرشاشة")
    assert [event.action_text for event in events] == ["Tank Fire", "Sweeping Operations"]
    assert all(event.locations[0].village == "الخيام" for event in events)
