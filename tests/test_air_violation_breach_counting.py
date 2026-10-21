from datetime import date, time

from app.news.services.air_violations.breach_counting_service import (
    BreachReport,
    BreachVillage,
    compute_breaches,
    count_breaches_by_condition,
)

DAY = date(2026, 10, 5)


def _village(
    village_id: int,
    caza: str,
    mohafaza: str,
    name: str | None = None,
) -> BreachVillage:
    return BreachVillage(
        village_id=village_id,
        name=name or f"Village {village_id}",
        caza_en=caza,
        mohafaza_en=mohafaza,
    )


def _report(
    report_id: int,
    condition_id: int,
    at: time,
    villages: tuple[BreachVillage, ...] = (),
    *,
    day: date = DAY,
    caza: str | None = None,
) -> BreachReport:
    return BreachReport(
        id=report_id,
        condition_id=condition_id,
        event_date=day,
        event_time=at,
        caza_en=caza,
        villages=villages,
    )


def _count(reports: list[BreachReport], condition_id: int) -> int:
    return count_breaches_by_condition(compute_breaches(reports))[condition_id]


NAB = ("Nabatiye", "Nabatiye")
SOUTH = ("Sour", "South")


def test_warplane_reports_in_one_mohafaza_within_window_count_once() -> None:
    reports = [
        _report(i, 35, time(10, i * 2), (_village(i, *NAB),)) for i in range(5)
    ]
    assert _count(reports, 35) == 1


def test_warplane_report_past_window_from_anchor_opens_new_breach() -> None:
    reports = [
        _report(i, 35, time(10, i * 2), (_village(i, *NAB),)) for i in range(5)
    ]
    reports.append(_report(9, 35, time(10, 11), (_village(9, *NAB),)))
    assert _count(reports, 35) == 2


def test_warplane_window_is_anchored_not_sliding() -> None:
    reports = [
        _report(1, 35, time(10, 0), (_village(1, *NAB),)),
        _report(2, 35, time(10, 10), (_village(2, *NAB),)),
        _report(3, 35, time(10, 18), (_village(3, *NAB),)),
    ]
    assert _count(reports, 35) == 2


def test_warplane_report_spanning_two_mohafazat_counts_each() -> None:
    reports = [
        _report(1, 35, time(10, 0), (_village(1, *NAB), _village(2, *SOUTH))),
    ]
    assert _count(reports, 35) == 2


def test_warplane_reports_in_different_mohafazat_do_not_share_a_window() -> None:
    reports = [
        _report(1, 35, time(10, 0), (_village(1, *NAB),)),
        _report(2, 35, time(10, 3), (_village(2, *SOUTH),)),
    ]
    assert _count(reports, 35) == 2


def test_warplane_without_village_falls_back_to_row_caza_mohafaza() -> None:
    reports = [
        _report(1, 35, time(10, 0), caza="Bint Jubail"),
        _report(2, 35, time(10, 4), (_village(2, *NAB),)),
    ]
    breaches = compute_breaches(reports)
    assert len(breaches) == 1
    assert breaches[0].unit_key == "Nabatiye"


def test_warplane_without_any_location_is_counted_and_flagged() -> None:
    breaches = compute_breaches([_report(1, 35, time(10, 0))])
    assert len(breaches) == 1
    assert breaches[0].needs_review is True
    assert breaches[0].unit_key == "Unknown"


def test_drone_in_six_hour_caza_uses_anchored_six_hour_windows() -> None:
    reports = [
        _report(1, 36, time(8, 0), (_village(1, "Sour", "South"),)),
        _report(2, 36, time(13, 59), (_village(2, "Sour", "South"),)),
        _report(3, 36, time(14, 1), (_village(3, "Sour", "South"),)),
    ]
    assert _count(reports, 36) == 2


def test_drone_in_hasbaya_counts_once_per_calendar_day() -> None:
    reports = [
        _report(i, 36, time(6 + i, 0), (_village(i, "Hasbaiya", "Nabatiye"),))
        for i in range(4)
    ]
    assert _count(reports, 36) == 1
    reports.append(
        _report(9, 36, time(7, 0), (_village(9, "Hasbaiya", "Nabatiye"),),
                day=date(2026, 10, 6))
    )
    assert _count(reports, 36) == 2


def test_drone_in_unlisted_caza_splits_at_midnight() -> None:
    reports = [
        _report(1, 36, time(23, 50), (_village(1, "Zahle", "Bekaa"),)),
        _report(2, 36, time(23, 55), (_village(2, "Zahle", "Bekaa"),)),
        _report(3, 36, time(0, 10), (_village(3, "Zahle", "Bekaa"),),
                day=date(2026, 10, 6)),
    ]
    assert _count(reports, 36) == 2


def test_drone_report_naming_two_cazas_counts_each() -> None:
    reports = [
        _report(1, 36, time(9, 0), (
            _village(1, "Sour", "South"),
            _village(2, "Bint Jbeil", "Nabatiye"),
        )),
    ]
    assert _count(reports, 36) == 2


def test_drone_without_village_uses_row_caza() -> None:
    reports = [
        _report(1, 36, time(9, 0), caza="Tyre"),
        _report(2, 36, time(10, 0), caza="Sour"),
    ]
    breaches = compute_breaches(reports)
    assert len(breaches) == 1
    assert breaches[0].window_minutes == 360


def test_drone_window_minutes_distinguish_six_hour_and_daily() -> None:
    breaches = compute_breaches([
        _report(1, 36, time(9, 0), caza="Sour"),
        _report(2, 36, time(9, 0), caza="Hasbaya"),
    ])
    minutes = {b.unit_key: b.window_minutes for b in breaches}
    assert minutes == {"Sour": 360, "Hasbaya": 1440}


def test_helicopter_report_counts_per_village() -> None:
    reports = [
        _report(1, 38, time(9, 0), (
            _village(1, "Sour", "South"),
            _village(2, "Sour", "South"),
            _village(3, "Sour", "South"),
        )),
    ]
    assert _count(reports, 38) == 3


def test_helicopter_reports_for_same_village_are_never_merged() -> None:
    reports = [
        _report(1, 38, time(9, 0), (_village(1, "Sour", "South"),)),
        _report(2, 38, time(9, 5), (_village(1, "Sour", "South"),)),
    ]
    breaches = compute_breaches(reports)
    assert len(breaches) == 2
    assert len({b.id for b in breaches}) == 2


def test_helicopter_without_village_counts_row_caza_once_per_report() -> None:
    reports = [_report(1, 38, time(9, 0), caza="Sour")]
    breaches = compute_breaches(reports)
    assert len(breaches) == 1
    assert breaches[0].unit_type == "caza"


def test_spy_balloon_report_naming_two_cazas_counts_two() -> None:
    reports = [
        _report(1, 34, time(9, 0), (
            _village(1, "Sour", "South"),
            _village(2, "Marjaayoun", "Nabatiye"),
        )),
    ]
    assert _count(reports, 34) == 2


def test_spy_balloon_same_caza_twice_counts_twice() -> None:
    reports = [
        _report(1, 34, time(9, 0), (_village(1, "Sour", "South"),)),
        _report(2, 34, time(9, 2), (_village(2, "Sour", "South"),)),
    ]
    assert _count(reports, 34) == 2


def test_null_event_time_is_treated_as_midnight() -> None:
    reports = [
        BreachReport(1, 35, DAY, None, villages=(_village(1, *NAB),)),
        _report(2, 35, time(0, 9), (_village(2, *NAB),)),
    ]
    assert _count(reports, 35) == 1


def test_counts_include_every_condition_key() -> None:
    assert count_breaches_by_condition([]) == {34: 0, 35: 0, 36: 0, 38: 0}


def test_breach_ids_are_stable_across_calls() -> None:
    reports = [
        _report(1, 35, time(10, 0), (_village(1, *NAB),)),
        _report(2, 36, time(10, 0), caza="Sour"),
    ]
    first = [b.id for b in compute_breaches(reports)]
    second = [b.id for b in compute_breaches(list(reversed(reports)))]
    assert first == second
