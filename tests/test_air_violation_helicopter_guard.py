from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.news.dtos import MatchResultDTO, MatchResultStatus, VillageMatchResult
from app.news.models import AirViolation, MessageStatus
from app.news.repositories.air_violation_repository import AirViolationRepository

VILLAGE = SimpleNamespace(
    id=7,
    ref_name_en="Bint Jbeil",
    ref_name_ar="بنت جبيل",
    acs_name=None,
    cad_name=None,
    caza_en="Bint Jubail",
    caza_ar="بنت جبيل",
)


def _result(condition_id: int, text: str) -> MatchResultDTO:
    return MatchResultDTO(
        village_matches=[
            VillageMatchResult(
                matched_village_id=7,
                village_confidence=1.0,
                village_match_status=MatchResultStatus.matched,
                village_review_required=False,
                raw_village_text="بنت جبيل",
            )
        ],
        any_village_low_confidence=False,
        matched_condition_id=condition_id,
        condition_confidence=1.0,
        condition_match_status=MatchResultStatus.matched,
        condition_review_required=False,
        raw_condition_text=text,
    )


def _message(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        source_id=1,
        external_message_id=None,
        source_platform="telegram",
        raw_text=text,
        raw_payload={},
        filter_result=None,
        status=MessageStatus.parsed,
        error_message=None,
        message_datetime=datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc),
        received_at=None,
    )


def _repository() -> tuple[AirViolationRepository, MagicMock]:
    db = MagicMock()
    db.scalar.return_value = None
    db.scalars.return_value.all.return_value = []
    db.execute.return_value.all.return_value = []
    db.get.side_effect = lambda model, key: (
        VILLAGE if key == 7 else SimpleNamespace(action_ar="خرق جوي", action_en="x")
    )
    return AirViolationRepository(db), db


def _written_condition(db: MagicMock) -> int | None:
    for call in db.add.call_args_list:
        row = call.args[0]
        if isinstance(row, AirViolation):
            return row.condition_id
    return None


def test_llm_helicopter_label_on_drone_only_text_is_written_as_surveillance():
    repository, db = _repository()
    text = "مسيرة معادية تحلق فوق بنت جبيل"

    assert repository.route_from_match(_message(text), _result(38, text)) is True
    assert _written_condition(db) == 36


def test_llm_helicopter_label_without_helicopter_word_is_not_written_as_helicopter():
    repository, db = _repository()
    text = "طائرة تحلق فوق صور"
    message = _message(text)

    assert repository.route_from_match(message, _result(38, text)) is False
    assert _written_condition(db) is None
    assert message.filter_result["air_violation_rejected"]["reason"] == (
        "helicopter label without helicopter keyword"
    )
    assert message.status == MessageStatus.rejected


def test_helicopter_keyword_text_is_written_as_helicopter():
    repository, db = _repository()
    text = "اباتشي تحلق فوق الناقورة"

    assert repository.route_from_match(_message(text), _result(38, text)) is True
    assert _written_condition(db) == 38


def test_text_with_both_helicopter_and_drone_words_records_both_term_sets():
    repository, db = _repository()
    text = "مروحية ومسيرة معادية تحلقان فوق بنت جبيل"
    message = _message(text)

    assert repository.route_from_match(message, _result(38, text)) is True
    assert _written_condition(db) == 36
    assert message.filter_result["air_aircraft_terms"]["helicopter_terms"]
    assert message.filter_result["air_aircraft_terms"]["drone_terms"]
