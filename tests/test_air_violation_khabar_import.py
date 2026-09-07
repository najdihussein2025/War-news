import json
from datetime import date
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from openpyxl import Workbook

from app.news.models import AirViolation, RawMessage, Village
from app.news.services.air_violations.air_violation_khabar_import import AirViolationKhabarImportService, read_khabar_rows


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
    assert (result.processed, result.succeeded, result.failed) == (4, 2, 2)
    records = [call.args[0] for call in db.add.call_args_list if isinstance(call.args[0], AirViolation)]
    assert records[0].condition_id == 36
    assert records[0].caza_en == 'Nabatiye'
    assert records[0].event_date == date(2026, 9, 7)
    assert records[0].event_time is None
    assert records[1].event_date == date(2026, 8, 1)
    messages = [call.args[0] for call in db.add.call_args_list if isinstance(call.args[0], RawMessage)]
    assert messages[0].match_result['village_matches'][0]['matched_village_id'] == 7
    assert [error.row for error in result.row_errors] == [4, 5]
