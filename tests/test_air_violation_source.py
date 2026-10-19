import os
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete as sa_delete, func, select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
from app.news.dtos import AirViolationListParams, MatchResultDTO, MatchResultStatus, VillageMatchResult
from app.news.models import AirViolation, Condition, MessageStatus, RawMessage, Village
from app.news.repositories.air_violation_repository import (
    AirViolationRepository,
    air_violation_caza_labels,
    air_violation_caza_window_hours,
    air_violation_news_text,
    as_beirut_datetime,
    clean_air_violation_news,
)
from app.sources.models import Source, SourceType


def test_air_violation_converts_telegram_utc_time_to_beirut() -> None:
    occurred_at = datetime(2026, 8, 20, 8, 55, tzinfo=timezone.utc)

    local = as_beirut_datetime(occurred_at)

    assert local.date() == date(2026, 8, 20)
    assert local.time().replace(tzinfo=None) == datetime(2026, 8, 20, 11, 55).time()


def test_image_ocr_news_is_replaced_with_clean_summary() -> None:
    message = type("Message", (), {
        "raw_payload": {"ocr_text": "garbled"},
        "raw_text": "Nabatieh مسيرة حيطة وحذر OCR garbage",
    })()
    village = type("Village", (), {"caza_ar": "النبطية", "caza_en": "Nabatiye"})()
    condition = type("Condition", (), {"action_ar": "طيران استطلاعي"})()

    assert air_violation_news_text(message, village, condition) == (
        "طيران استطلاعي في قضاء النبطية - حيطة وحذر"
    )


def test_image_ocr_news_uses_multi_region_when_villages_span_cazas() -> None:
    message = type("Message", (), {
        "raw_payload": {"ocr_text": "Adloun Maarakeh"},
        "raw_text": "redalert.com.lb \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
    })()
    adloun = type("Village", (), {
        "ref_name_ar": "\u0639\u062f\u0644\u0648\u0646",
        "ref_name_en": "Adloun",
        "acs_name": None,
        "cad_name": None,
        "caza_ar": "\u0635\u064a\u062f\u0627",
        "caza_en": "Saida",
    })()
    maarakeh = type("Village", (), {
        "ref_name_ar": "\u0645\u0639\u0631\u0643\u0629",
        "ref_name_en": "Maarake",
        "acs_name": None,
        "cad_name": None,
        "caza_ar": "\u0635\u0648\u0631",
        "caza_en": "Sour",
    })()
    condition = type("Condition", (), {
        "action_ar": "\u0637\u064a\u0631\u0627\u0646 \u0627\u0633\u062a\u0637\u0644\u0627\u0639\u064a",
    })()

    text = air_violation_news_text(message, adloun, condition, [adloun, maarakeh])

    assert "\u0645\u0646\u0627\u0637\u0642 \u0645\u062a\u0639\u062f\u062f\u0629" in text
    assert "\u0642\u0636\u0627\u0621 \u0635\u064a\u062f\u0627" not in text


def test_written_news_removes_decorative_symbol_lines_but_keeps_text() -> None:
    value = "🚫\nإطباق جوي واسع\n⛔️\nأقصى درجات الحيطة والحذر\n⛔️"

    assert clean_air_violation_news(value) == (
        "إطباق جوي واسع\nأقصى درجات الحيطة والحذر"
    )


def test_air_violation_news_text_strips_inline_emoji_from_raw_text() -> None:
    message = type("Message", (), {
        "raw_payload": {},
        "raw_text": "🚨 طيران حربي فوق الجنوب 🔴",
    })()

    assert air_violation_news_text(message, None, None) == "طيران حربي فوق الجنوب"


def test_multi_region_bulletin_does_not_get_a_false_single_caza() -> None:
    labels = air_violation_caza_labels(
        "الجنوب: النبطية والجوار\nخط الساحل / بيروت\nالهرمل",
        "Akkar",
        "عكار",
        [("Nabatiye", "النبطية"), ("Beirut", "بيروت"), ("Hermel", "الهرمل")],
    )

    assert labels == ("Multiple regions", "مناطق متعددة")


def test_south_lebanon_air_alert_keeps_south_lebanon_label() -> None:
    labels = air_violation_caza_labels(
        "#مقاتلات_حربية #الجنوب الخريطة المباشرة",
        None,
        None,
        [("Nabatiye", "النبطية"), ("Sour", "صور"), ("Bint Jubail", "بنت جبيل")],
    )

    assert labels == ("South Lebanon", "جنوب لبنان")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("drone activity over hermel", ("Hermel", "الهرمل")),
        ("warplanes over baalbeck", ("Baalbek", "بعلبك")),
        ("surveillance aircraft over saida", ("Saida", "صيدا")),
        ("drone patrol over west beqaa", ("West Bekaa", "البقاع الغربي")),
    ],
)
def test_air_violation_caza_aliases_include_requested_kadaa(text, expected) -> None:
    labels = air_violation_caza_labels(
        text,
        None,
        None,
        [
            ("Hermel", "الهرمل"),
            ("Baalbek", "بعلبك"),
            ("Saida", "صيدا"),
            ("West Bekaa", "البقاع الغربي"),
        ],
    )

    assert labels == expected


@pytest.mark.parametrize(
    ("caza_en", "condition_id", "expected_hours"),
    [
        ("Nabatiye", 35, 4),
        ("Marjaayoun", 35, 4),
        ("Bint Jbeil", 35, 4),
        ("Tyre", 35, 4),
        ("Sour", 35, 4),
        ("Baabda", 35, 4),
        ("Hermel", 35, 4),
        ("Baalbeck", 35, 4),
        ("Saida", 35, 4),
        ("West Beqaa", 35, 4),
        ("Akkar", 35, 4),
        (None, 35, 4),
        ("Nabatiye", 36, 1),
        ("Akkar", 36, 4),
        ("Koura", 36, 4),
        ("Nabatiye", 38, 1),
        ("Akkar", 38, 1),
    ],
)
def test_air_violation_caza_window_hours(caza_en, condition_id, expected_hours) -> None:
    assert air_violation_caza_window_hours(caza_en, condition_id) == expected_hours


def test_telegram_message_identity_bypasses_recent_similarity_suppression() -> None:
    message = type("Message", (), {
        "external_message_id": "telegram:redlinkleb:12345",
        "source_platform": "telegram",
        "raw_payload": {},
    })()

    assert AirViolationRepository._has_strong_message_identity(message) is True


def test_telegram_identity_does_not_bypass_for_caza_only_air_alert() -> None:
    message = type("Message", (), {
        "external_message_id": "telegram:redlinkleb:12345",
        "source_platform": "telegram",
        "raw_payload": {},
    })()
    result = MatchResultDTO(
        village_matches=[],
        any_village_low_confidence=False,
        matched_condition_id=35,
        condition_confidence=1.0,
        condition_match_status=MatchResultStatus.matched,
        condition_review_required=False,
        raw_condition_text="#مقاتلات_حربية #الجنوب",
    )

    assert AirViolationRepository._should_bypass_recent_duplicate_check(message, result) is False


def test_telegram_identity_bypasses_for_location_specific_air_alert() -> None:
    message = type("Message", (), {
        "external_message_id": "telegram:redlinkleb:12345",
        "source_platform": "telegram",
        "raw_payload": {},
    })()
    result = MatchResultDTO(
        village_matches=[
            VillageMatchResult(
                matched_village_id=7,
                village_confidence=1.0,
                village_match_status=MatchResultStatus.matched,
                village_review_required=False,
                raw_village_text="Maarake",
            )
        ],
        any_village_low_confidence=False,
        matched_condition_id=36,
        condition_confidence=1.0,
        condition_match_status=MatchResultStatus.matched,
        condition_review_required=False,
        raw_condition_text="Drone over Maarake",
    )

    assert AirViolationRepository._should_bypass_recent_duplicate_check(message, result) is True


def test_priority_caza_air_violations_are_preserved_and_collapsed_per_hour() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for repository integration coverage.")

    engine = create_engine(database_url)
    try:
        connection = engine.connect()
    except OperationalError as exc:
        pytest.skip(f"Database is unavailable: {exc}")

    transaction = connection.begin()
    db = Session(bind=connection, join_transaction_mode="create_savepoint")
    marker = uuid4().hex
    try:
        condition = db.get(Condition, 36)
        if condition is None:
            pytest.skip("Air-violation condition 36 is unavailable.")

        source = Source(
            type=SourceType.api,
            name="Red Alert Lebanon",
            external_id=f"air-window-source-{marker}",
            config={},
        )
        village = Village(
            acs_code=int(marker[:6], 16),
            ref_name_en=f"Arnoun Test {marker}",
            ref_name_ar=f"Arnoun Test {marker}",
            caza_en="Nabatiye",
            caza_ar="Nabatiye",
        )
        db.add_all([source, village])
        db.flush()

        def result() -> MatchResultDTO:
            return MatchResultDTO(
                village_matches=[
                    VillageMatchResult(
                        matched_village_id=village.id,
                        village_confidence=1.0,
                        village_match_status=MatchResultStatus.matched,
                        village_review_required=False,
                        raw_village_text=village.ref_name_en,
                    )
                ],
                any_village_low_confidence=False,
                matched_condition_id=condition.id,
                condition_confidence=1.0,
                condition_match_status=MatchResultStatus.matched,
                condition_review_required=False,
                raw_condition_text="drone over Nabatiye",
            )

        def message(suffix: str, occurred_at: datetime) -> RawMessage:
            item = RawMessage(
                source_id=source.id,
                external_message_id=f"air-window-message-{marker}-{suffix}",
                source_platform="telegram",
                source_name="red-alert",
                raw_text=f"drone over {village.ref_name_en}",
                raw_payload={},
                status=MessageStatus.parsed,
                message_datetime=occurred_at,
            )
            db.add(item)
            db.flush()
            return item

        repository = AirViolationRepository(db)
        first_at = datetime(2026, 9, 21, 8, 0, tzinfo=timezone.utc)
        db.execute(
            sa_delete(AirViolation).where(
                AirViolation.caza_en == "Nabatiye",
                AirViolation.event_date == first_at.astimezone().date(),
            )
        )
        db.flush()

        assert repository.route_from_match(message("first", first_at), result()) is True
        assert repository.route_from_match(
            message("inside-window", first_at + timedelta(minutes=59)),
            result(),
        ) is True
        assert repository.route_from_match(
            message("after-window", first_at + timedelta(hours=1, minutes=1)),
            result(),
        ) is True

        total = db.scalar(
            select(func.count(AirViolation.id)).where(
                AirViolation.caza_en == "Nabatiye",
                AirViolation.source_id == source.id,
            )
        )
        assert total == 3

        event_date = first_at.astimezone().date()
        displayed = repository.list_all(AirViolationListParams(
            caza_en="Nabatiye",
            event_date_from=event_date,
            event_date_to=event_date,
        ))
        own_windows = [
            item for item in displayed.items
            if item.source_id == source.id
        ]
        assert len(own_windows) == 2
        assert sorted(item.window_violation_count for item in own_windows) == [1, 2]
        assert sorted(len(item.window_reports) for item in own_windows) == [1, 2]
    except (OperationalError, ProgrammingError) as exc:
        pytest.skip(f"Air-violation schema is unavailable: {exc}")
    finally:
        db.close()
        transaction.rollback()
        connection.close()


def test_air_violation_uses_original_message_source_name() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for repository integration coverage.")

    engine = create_engine(database_url)
    try:
        connection = engine.connect()
    except OperationalError as exc:
        pytest.skip(f"Database is unavailable: {exc}")

    transaction = connection.begin()
    db = Session(bind=connection, join_transaction_mode="create_savepoint")
    marker = uuid4().hex
    try:
        condition = db.get(Condition, 35)
        if condition is None:
            pytest.skip("Air-violation condition 35 is unavailable.")

        source = Source(
            type=SourceType.api,
            name="CNRS Webhook",
            external_id=f"source-test-{marker}",
            config={},
        )
        db.add(source)
        db.flush()
        message = RawMessage(
            source_id=source.id,
            external_message_id=f"message-test-{marker}",
            source_platform="telegram",
            source_name="original-channel",
            origin_account="original-account",
            raw_payload={},
            status=MessageStatus.parsed,
        )
        db.add(message)
        db.flush()
        db.add(
            AirViolation(
                raw_message_id=message.id,
                condition_id=condition.id,
                source_id=source.id,
                caza_en=marker,
                event_date=date(2026, 8, 18),
                khabar="Source mapping test",
            )
        )
        db.flush()

        result = AirViolationRepository(db).list_all(
            AirViolationListParams(caza_en=marker)
        )

        assert result.total == 1
        assert result.items[0].source_name == "original-account"
    except (OperationalError, ProgrammingError) as exc:
        pytest.skip(f"Air-violation schema is unavailable: {exc}")
    finally:
        db.close()
        transaction.rollback()
        connection.close()


def test_red_alert_air_violation_displays_red_alert_source_name() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for repository integration coverage.")

    engine = create_engine(database_url)
    try:
        connection = engine.connect()
    except OperationalError as exc:
        pytest.skip(f"Database is unavailable: {exc}")

    transaction = connection.begin()
    db = Session(bind=connection, join_transaction_mode="create_savepoint")
    marker = uuid4().hex
    try:
        condition = db.get(Condition, 35)
        if condition is None:
            pytest.skip("Air-violation condition 35 is unavailable.")

        source = Source(
            type=SourceType.api,
            name="CNRS Webhook",
            external_id=f"red-alert-source-test-{marker}",
            config={},
        )
        db.add(source)
        db.flush()
        message = RawMessage(
            source_id=source.id,
            external_message_id=f"red-alert-message-test-{marker}",
            source_platform="telegram",
            source_name="Red Alert Lebanon",
            origin_account="@redlinkleb",
            raw_payload={},
            status=MessageStatus.parsed,
        )
        db.add(message)
        db.flush()
        db.add(
            AirViolation(
                raw_message_id=message.id,
                condition_id=condition.id,
                source_id=source.id,
                caza_en=marker,
                event_date=date(2026, 8, 18),
                khabar="Red Alert source display test",
            )
        )
        db.flush()

        result = AirViolationRepository(db).list_all(
            AirViolationListParams(caza_en=marker)
        )

        assert result.total == 1
        assert result.items[0].source_name == "Red Alert Lebanon"
    except (OperationalError, ProgrammingError) as exc:
        pytest.skip(f"Air-violation schema is unavailable: {exc}")
    finally:
        db.close()
        transaction.rollback()
        connection.close()
