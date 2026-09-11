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
    assert 'condition_id IN (35, 36, 38)' in sql


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


def test_condition_45_is_not_routed_to_air_violations():
    db = MagicMock()
    result = AirViolationRepository(db).route_from_match(
        SimpleNamespace(), SimpleNamespace(matched_condition_id=45)
    )
    assert result is False
    assert db.mock_calls == []
