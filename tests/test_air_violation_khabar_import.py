import json
from datetime import date, datetime, time
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from openpyxl import Workbook

from app.news.models import AirViolation, RawMessage, Village
from app.news.services.air_violations.air_violation_khabar_import import AirViolationKhabarImportService, parse_event_date, read_khabar_rows


@pytest.mark.parametrize('value, expected', [
    (None, date(2026, 9, 7)),
    ('  ', date(2026, 9, 7)),
    (datetime(2026, 8, 1, 12), date(2026, 8, 1)),
    ('2026-08-01', date(2026, 8, 1)),
    ('01/08/2026', date(2026, 8, 1)),
    ('31-08-2026', date(2026, 8, 31)),
])
def test_import_dates(value, expected):
    assert parse_event_date(value, date(2026, 9, 7)) == expected


def test_invalid_date_is_actionable():
    with pytest.raises(ValueError, match='Date must be'):
        parse_event_date('31/02/2026', date(2026, 9, 7))


def test_excel_import_preserves_metadata_and_keeps_lookup_loaded():
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import Session

    engine = create_engine('sqlite://')
    Village.__table__.create(engine)
    with Session(engine) as lookup_db:
        lookup_db.add(Village(id=7, acs_code=700, ref_name_en='Arnoun', caza_en='Nabatiye'))
        lookup_db.commit()
        villages = lookup_db.query(Village).all()
        queries = []
        event.listen(engine, 'before_cursor_execute', lambda *args: queries.append(args[2]))
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None
        db.scalars.return_value.all.return_value = villages
        db.expunge.side_effect = lookup_db.expunge
        db.commit.side_effect = lookup_db.commit
        db.scalar.return_value = SimpleNamespace(id=1)
        db.get.return_value = SimpleNamespace(id=36)
        workbook = Workbook()
        workbook.active.append(['Khabar', 'Date', 'Time', 'Source', 'Note 1', 'Note 2', 'Link'])
        for _ in range(2):
            workbook.active.append(['طيران استطلاعي فوق Arnoun', '01/08/2026', time(14, 30), 'File source', 'First note', 'Second note', 'https://example.com/news'])
        stream = BytesIO()
        workbook.save(stream)
        stream.seek(0)
        result = AirViolationKhabarImportService(db).import_file(stream, 'news.xlsx', date(2026, 9, 7))
        assert (result.succeeded, result.failed) == (2, 0)
        records = [call.args[0] for call in db.add.call_args_list if isinstance(call.args[0], AirViolation)]
        assert records[0].event_date == date(2026, 8, 1)
        assert records[0].event_time == time(14, 30)
        assert records[0].note_1 == 'First note'
        assert records[0].note_2 == 'Second note'
        assert records[0].source_link == 'https://example.com/news'
        assert records[0].condition_id == 36
        assert queries == []


def test_reads_only_khabar_excel_column():
    workbook = Workbook()
    workbook.active.append([' Khabar '])
    workbook.active.append(['طيران استطلاعي فوق أرنون'])
    stream = BytesIO()
    workbook.save(stream)
    stream.seek(0)
    assert read_khabar_rows(stream, 'news.xlsx') == [{'khabar': 'طيران استطلاعي فوق أرنون'}]


def test_reads_geojson_properties():
    data = {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'geometry': None, 'properties': {'Khabar': 'news'}},
    ]}
    assert read_khabar_rows(BytesIO(json.dumps(data).encode()), 'news.geojson') == [{'khabar': 'news'}]


@pytest.mark.parametrize('content', [b'bad json', b'42', b'[null]'])
def test_rejects_malformed_json(content):
    with pytest.raises(ValueError):
        read_khabar_rows(BytesIO(content), 'news.json')


def test_classifies_news_and_reports_unmatched_rows():
    village = Village(id=7, acs_code=700, ref_name_ar='أرنون', ref_name_en='Arnoun', caza_en='Nabatiye', caza_ar='النبطية')
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = None
    db.scalars.return_value.all.return_value = [village]
    db.scalar.return_value = SimpleNamespace(id=1)
    db.get.return_value = SimpleNamespace(id=36)
    def assign_id(value):
        if isinstance(value, RawMessage):
            value.id = 99
    db.add.side_effect = assign_id
    rows = [
        {'Khabar': 'طيران استطلاعي فوق أرنون'},
        {'Khabar': 'طيران استطلاعي فوق أرنون', 'Date': '2026-08-01'},
        {'Khabar': 'طيران استطلاعي فوق مكان غير معروف'},
        {'Khabar': 'خبر عن الطقس'},
    ]
    result = AirViolationKhabarImportService(db).import_file(
        BytesIO(json.dumps(rows).encode()), 'news.json', date(2026, 9, 7),
    )
    assert (result.processed, result.succeeded, result.failed) == (4, 3, 1)
    records = [call.args[0] for call in db.add.call_args_list if isinstance(call.args[0], AirViolation)]
    assert records[0].condition_id == 36
    assert records[0].caza_en == 'Nabatiye'
    assert records[0].event_date == date(2026, 9, 7)
    assert records[0].event_time is None
    assert records[1].event_date == date(2026, 8, 1)
    messages = [call.args[0] for call in db.add.call_args_list if isinstance(call.args[0], RawMessage)]
    assert messages[0].match_result['village_matches'][0]['matched_village_id'] == 7
    assert records[2].caza_en is None
    assert records[2].caza_ar is None
    assert messages[2].match_result['village_matches'] == []
    assert [error.row for error in result.row_errors] == [5]


@pytest.mark.parametrize('caza, english, arabic', [('Custom district', 'Custom district', None), ('بيروت', None, 'بيروت'), (None, None, None)])
def test_import_without_village_preserves_supplied_caza(caza, english, arabic):
    db = MagicMock()
    db.scalars.return_value.all.return_value = []
    db.scalar.return_value = SimpleNamespace(id=1)
    db.execute.return_value.scalar_one_or_none.return_value = None
    rows = [{'Khabar': 'طيران استطلاعي في المنطقة', 'Caza': caza}]
    result = AirViolationKhabarImportService(db).import_file(
        BytesIO(json.dumps(rows).encode()), 'news.json', date(2026, 9, 7))
    assert (result.succeeded, result.failed) == (1, 0)
    record = next(call.args[0] for call in db.add.call_args_list if isinstance(call.args[0], AirViolation))
    assert (record.caza_en, record.caza_ar) == (english, arabic)
    assert record.condition_id == 36
    assert record.khabar == rows[0]['Khabar']


def test_retry_skips_previously_imported_record():
    db = MagicMock()
    db.scalars.return_value.all.return_value = []
    db.scalar.return_value = SimpleNamespace(id=1)
    db.execute.return_value.scalar_one_or_none.return_value = 123
    rows = [{'Khabar': 'طيران استطلاعي في المنطقة'}]
    result = AirViolationKhabarImportService(db).import_file(
        BytesIO(json.dumps(rows).encode()), 'news.json', date(2026, 9, 7))
    assert (result.processed, result.succeeded, result.skipped, result.failed) == (1, 0, 1, 0)
    db.add.assert_not_called()
    # Inferred geography/classification can improve between retries without
    # turning the same file row into another imported record.
    from sqlalchemy.dialects import postgresql
    sql = str(db.execute.call_args.args[0].compile(dialect=postgresql.dialect()))
    assert 'air_violations.caza_en =' not in sql
    assert 'air_violations.caza_ar =' not in sql
    assert 'air_violations.condition_id =' not in sql
    assert 'air_violations.source_link IS NULL' in sql


@pytest.mark.parametrize('file_date, file_time, expected_date, expected_time', [
    (None, None, date(2026, 8, 2), time(0, 30)),
    ('2026-08-01', '12:00', date(2026, 8, 1), time(12)),
])
def test_source_enrichment_fills_only_missing_dates_and_times(monkeypatch, file_date, file_time, expected_date, expected_time):
    from app.news.services.air_violations.import_source_enrichment import ImportSourceLookup
    monkeypatch.setattr(ImportSourceLookup, 'lookup', lambda self, link: {
        'status': 'retrieved', 'published_at': '2026-08-01T21:30:00+00:00', 'text': 'Source text',
    })
    db = MagicMock()
    db.scalars.return_value.all.return_value = []
    db.scalar.return_value = SimpleNamespace(id=1)
    db.execute.return_value.scalar_one_or_none.return_value = None
    row = {'Khabar': 'مسير المنزلة', 'Date': file_date, 'Time': file_time, 'Link': 'https://t.me/channel/42'}
    result = AirViolationKhabarImportService(db).import_file(BytesIO(json.dumps([row]).encode()), 'news.json', date(2026, 9, 9))
    assert result.succeeded == 1
    record = next(call.args[0] for call in db.add.call_args_list if isinstance(call.args[0], AirViolation))
    assert (record.event_date, record.event_time) == (expected_date, expected_time)
    assert record.khabar == row['Khabar']
    from sqlalchemy.dialects import postgresql
    sql = str(db.execute.call_args.args[0].compile(dialect=postgresql.dialect()))
    assert 'air_violations.event_date =' not in sql
