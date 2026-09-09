from app.news.repositories.incident_repository import IncidentRepository


def test_casualty_review_reasons_remain_user_visible() -> None:
    assert IncidentRepository._is_casualty_review_reason(
        "Category casualties require manual per-village confirmation"
    )
    assert IncidentRepository._is_casualty_review_reason(
        "Unsupported casualty_scope=bulletin_aggregate: evidence matched 1 target village(s)"
    )
    assert not IncidentRepository._is_casualty_review_reason(
        "Possible duplicate detected during detail extraction"
    )
