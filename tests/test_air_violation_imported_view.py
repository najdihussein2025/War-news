from datetime import date, datetime, time
from types import SimpleNamespace
from unittest.mock import MagicMock

from sqlalchemy.dialects import postgresql

from app.news.dtos import AirViolationListParams
from app.news.repositories.air_violation_repository import AirViolationRepository


def test_import_filter_does_not_require_join_in_summary_or_count():
    filters = AirViolationRepository._filters(AirViolationListParams(imported_only=True))
    assert len(filters) == 2
    sql = str(filters[1].compile(dialect=postgresql.dialect(), compile_kwargs={'literal_binds': True}))
    assert 'raw_message_id IN (SELECT raw_messages.id' in sql
    assert 'khabar' in sql
    default_filters = AirViolationRepository._filters(AirViolationListParams())
    sql = str(default_filters[0].compile(compile_kwargs={'literal_binds': True}))
    assert 'condition_id IN (34, 35, 36, 38)' in sql


def test_import_details_preserve_file_fields():
    row = SimpleNamespace(_mapping={
        'import_payload': {'import': 'khabar', 'filename': 'news.xlsx', 'row': {'khabar': 'news', 'custom column': 'original'}},
        'raw_match_result': {}, 'caza_en': None, 'caza_ar': None,
    })
    result = AirViolationRepository(MagicMock())._with_village_labels([row])[0]
    assert result['is_imported'] is True
    assert result['import_filename'] == 'news.xlsx'
    assert result['import_row']['custom column'] == 'original'
    assert 'import_payload' not in result


def test_village_labels_do_not_override_stored_multi_region_caza():
    row = SimpleNamespace(_mapping={
        'id': 42,
        'village_id': 7,
        'import_payload': {},
        'raw_match_result': {},
        'caza_en': 'Multiple regions',
        'caza_ar': 'مناطق متعددة',
    })
    village = SimpleNamespace(
        id=7,
        ref_name_en='Aadloun',
        ref_name_ar='عدلون',
        acs_name=None,
        cad_name=None,
        caza_en='Saida',
        caza_ar='صيدا',
    )
    db = MagicMock()
    db.execute.return_value.all.return_value = []
    db.scalars.return_value = [village]

    result = AirViolationRepository(db)._with_village_labels([row])[0]

    assert result['caza_en'] == 'Multiple regions'
    assert result['caza_ar'] == 'مناطق متعددة'
    assert result['village_en'] == 'Aadloun'


def _item(
    item_id: int,
    condition_id: int,
    at: time,
    *,
    caza: str | None = "Sour",
    villages: list[dict] | None = None,
    day: date = date(2026, 9, 22),
    khabar: str = "report",
) -> dict:
    return {
        "id": item_id, "condition_id": condition_id, "caza_en": caza, "caza_ar": None,
        "event_date": day, "event_time": at, "villages": villages or [],
        "khabar": khabar, "source_name": f"Source {item_id}", "source_link": None,
        "window_id": None,
    }


def _village(village_id: int, name: str, caza: str, mohafaza: str) -> dict:
    return {
        "village_id": village_id, "name": name,
        "caza_en": caza, "caza_ar": None, "mohafaza_en": mohafaza, "mohafaza_ar": None,
    }


def test_drone_reports_in_one_window_become_one_list_item_with_all_villages():
    items = [
        _item(2, 36, time(10, 30), villages=[_village(2, "Maarakeh", "Sour", "South")]),
        _item(1, 36, time(10, 0), villages=[_village(1, "Aadloun", "Sour", "South")]),
    ]

    result = AirViolationRepository._build_display_items(items, items)

    assert len(result) == 1
    assert result[0]["id"] == 1
    assert result[0]["window_violation_count"] == 2
    assert result[0]["window_duration_minutes"] == 360
    assert result[0]["villages"] == [
        {"village_id": 1, "name": "Aadloun"},
        {"village_id": 2, "name": "Maarakeh"},
    ]
    assert [report["id"] for report in result[0]["window_reports"]] == [1, 2]


def test_warplane_reports_collapse_into_ten_minute_windows():
    south = [_village(1, "Tyre", "Sour", "South")]
    items = [
        _item(1, 35, time(10, 0), villages=south),
        _item(2, 35, time(10, 9), villages=south),
        _item(3, 35, time(10, 11), villages=south),
    ]

    result = AirViolationRepository._build_display_items(items, items)

    assert sorted(item["window_violation_count"] for item in result) == [1, 2]
    assert {item["window_duration_minutes"] for item in result} == {10}


def test_warplane_report_spanning_mohafazat_appears_once_per_window():
    items = [_item(1, 35, time(10, 0), villages=[
        _village(1, "Arnoun", "Nabatiye", "Nabatiye"),
        _village(2, "Tyre", "Sour", "South"),
    ])]

    result = AirViolationRepository._build_display_items(items, items)

    assert len(result) == 2
    assert {item["unit_type"] for item in result} == {"mohafaza"}


def test_window_context_includes_reports_outside_the_visible_filter():
    visible = _item(2, 36, time(13, 30), caza="Koura",
                    villages=[_village(2, "Amioun", "Koura", "North")])
    earlier = _item(1, 36, time(10, 0), caza="Koura",
                    villages=[_village(1, "Kfar Hazir", "Koura", "North")])

    result = AirViolationRepository._build_display_items([earlier, visible], [visible, earlier])
    assert len(result) == 1
    assert result[0]["window_violation_count"] == 2
    assert result[0]["window_duration_minutes"] == 1440

    # The anchor lies outside the filter, so the window belongs to another period.
    assert AirViolationRepository._build_display_items([visible], [visible, earlier]) == []


def test_helicopter_item_reports_one_breach_per_village():
    items = [_item(1, 38, time(10, 0), villages=[
        _village(1, "A", "Sour", "South"),
        _village(2, "B", "Sour", "South"),
        _village(3, "C", "Sour", "South"),
    ])]

    result = AirViolationRepository._build_display_items(items, items)

    assert len(result) == 1
    assert result[0]["breach_count"] == 3
    assert result[0]["unit_type"] == "village"
    assert result[0]["window_id"] is None


def test_unconfirmed_surveillance_region_is_flagged_but_still_counted():
    items = [
        _item(2, 36, time(10, 30), caza="South Lebanon"),
        _item(1, 36, time(10, 0), caza="South Lebanon"),
    ]

    result = AirViolationRepository._build_display_items(items, items)

    assert len(result) == 1
    assert result[0]["window_violation_count"] == 2


def test_unsupported_condition_rows_pass_through_unchanged():
    items = [_item(1, 45, time(10, 0))]

    result = AirViolationRepository._build_display_items(items, items)

    assert [item["id"] for item in result] == [1]
    assert result[0].get("breach_count") is None


def _summary_repository(items: list[dict], context: list[dict] | None = None) -> AirViolationRepository:
    repository = AirViolationRepository(MagicMock())
    repository._load_items = MagicMock(side_effect=[items] + ([context] if context is not None else []))
    return repository


def test_summary_counts_breaches_not_rows():
    south = [_village(1, "Tyre", "Sour", "South")]
    items = [
        *[_item(i, 35, time(10, i), villages=south) for i in range(1, 6)],
        _item(10, 36, time(8, 0), villages=south),
        _item(11, 36, time(9, 0), villages=south),
        _item(12, 38, time(9, 0), villages=[
            _village(1, "A", "Sour", "South"), _village(2, "B", "Sour", "South"),
        ]),
        _item(13, 34, time(9, 0), villages=[
            _village(1, "A", "Sour", "South"), _village(5, "C", "Bint Jbeil", "Nabatiye"),
        ]),
    ]

    summary = _summary_repository(items).get_summary(AirViolationListParams())

    assert summary.warplanes == 1
    assert summary.surveillance_aircraft == 1
    assert summary.helicopters == 2
    assert summary.spy_balloons == 2


def test_summary_date_filter_cutting_a_six_hour_window_counts_it_once():
    south = [_village(1, "Tyre", "Sour", "South")]
    anchor = _item(1, 36, time(22, 0), villages=south, day=date(2026, 9, 21))
    next_day = _item(2, 36, time(2, 0), villages=south, day=date(2026, 9, 22))
    params = AirViolationListParams(event_date_from=date(2026, 9, 22), event_date_to=date(2026, 9, 22))

    # Filtered rows hold only the report after midnight; the context holds both.
    summary = _summary_repository([next_day], [anchor, next_day]).get_summary(params)

    # The window opened on the 21st, so it is not counted in the 22nd's cards.
    assert summary.surveillance_aircraft == 0

    params = AirViolationListParams(event_date_from=date(2026, 9, 21), event_date_to=date(2026, 9, 21))
    summary = _summary_repository([anchor], [anchor, next_day]).get_summary(params)
    assert summary.surveillance_aircraft == 1


def test_condition_45_is_not_routed_to_air_violations():
    db = MagicMock()
    result = AirViolationRepository(db).route_from_match(
        SimpleNamespace(), SimpleNamespace(matched_condition_id=45)
    )
    assert result is False
    assert db.mock_calls == []


def test_recent_duplicate_check_requires_same_news_text():
    existing = SimpleNamespace(
        condition_id=36,
        caza_en="Koura",
        caza_ar=None,
        event_date=date(2026, 9, 22),
        event_time=time(12, 58),
        khabar="Surveillance aircraft over Aaba",
    )
    db = MagicMock()
    db.scalars.return_value.all.return_value = [existing]
    repository = AirViolationRepository(db)

    assert repository._has_recent_air_violation(
        datetime(2026, 9, 22, 13, 5),
        condition_id=36,
        khabar="Surveillance aircraft over Aaba",
    )
    assert not repository._has_recent_air_violation(
        datetime(2026, 9, 22, 13, 5),
        condition_id=36,
        khabar="Surveillance aircraft over Kfar Hazir",
    )


def test_recent_duplicate_check_only_covers_ten_minutes():
    existing = SimpleNamespace(
        condition_id=35,
        caza_en="Sour",
        caza_ar=None,
        event_date=date(2026, 9, 22),
        event_time=time(12, 45),
        khabar="Warplanes over Sour",
    )
    db = MagicMock()
    db.scalars.return_value.all.return_value = [existing]
    repository = AirViolationRepository(db)

    assert repository._has_recent_air_violation(
        datetime(2026, 9, 22, 12, 52),
        condition_id=35,
        khabar="Warplanes over Sour",
    )
    assert not repository._has_recent_air_violation(
        datetime(2026, 9, 22, 13, 5),
        condition_id=35,
        khabar="Warplanes over Sour",
    )


def test_text_less_report_is_never_a_duplicate_of_a_nearby_caza_row():
    existing = SimpleNamespace(
        condition_id=35,
        caza_en="South Lebanon",
        caza_ar="جنوب لبنان",
        event_date=date(2026, 9, 28),
        event_time=time(10, 17),
        khabar="#مقاتلات_حربية #الجنوب <A>",
    )
    db = MagicMock()
    db.scalars.return_value.all.return_value = [existing]
    repository = AirViolationRepository(db)

    assert not repository._has_recent_air_violation(
        datetime(2026, 9, 28, 10, 20),
        condition_id=35,
        khabar=None,
    )
