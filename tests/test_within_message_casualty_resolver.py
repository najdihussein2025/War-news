from app.news.services.incident_details.within_message_casualty_resolver import CasualtyClaim, resolve_within_message_claims


def test_headline_equal_to_parts_is_not_added():
    result = resolve_within_message_claims([
        CasualtyClaim(deaths=9, injuries=13, quote="9/13", is_headline=True),
        CasualtyClaim(deaths=8, injuries=11, village="X", quote="8/11"),
        CasualtyClaim(deaths=1, injuries=2, village="Y", quote="1/2"),
    ])
    assert sum(item.deaths or 0 for item in result.claims) == 9
    assert result.conflict_reason is None


def test_specific_body_claim_wins_and_records_conflict():
    result = resolve_within_message_claims([
        CasualtyClaim(deaths=11, village="X", quote="headline", is_headline=True),
        CasualtyClaim(deaths=9, injuries=5, village="X", quote="body"),
    ])
    assert result.claims[0].deaths == 9
    assert "headline conflicts" in (result.conflict_reason or "")
    assert result.aggregate_remainder is not None


def test_repeated_identical_part_is_not_stacked():
    claim = CasualtyClaim(deaths=8, injuries=11, village="Kfarroumane", quote="8/11")
    result = resolve_within_message_claims([claim, claim])
    assert result.claims == (claim,)
    assert result.conflict_reason is None
