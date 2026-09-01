from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import os

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from app.sources.services.red_alert_collector import (
    HOURS_FETCH_LIMIT_CAP,
    RedAlertPost,
    RedAlertCollector,
    classify_condition,
    fetch_limit_for_hours,
    is_preview_boilerplate,
    match_village,
    parse_public_preview,
    posts_within_window,
)
from app.news.models import MessageStatus, RawMessage
from app.news.models.air_violation import AirViolation
from app.news.repositories.air_violation_repository import AirViolationRepository
from app.news.services.red_alert_air_violation_service import RedAlertAirViolationService
from app.sources.models import Source, SourceType


def test_rejects_air_violation_without_a_canonical_village() -> None:
    class _AirViolationRepository:
        routed = None

        def route_from_match(self, message, result) -> bool:
            self.routed = (message, result)
            return True

        discarded = False

        def discard_for_message(self, message) -> None:
            self.discarded = True

    repository = _AirViolationRepository()
    service = RedAlertAirViolationService(
        repository,  # type: ignore[arg-type]
        lambda text: 35,
        lambda text, villages: None,
    )
    message = SimpleNamespace(
        id=99,
        raw_text="warplanes over the south",
        raw_payload={},
        filter_result=None,
        match_result=None,
        status=MessageStatus.pending,
        error_message=None,
    )

    assert service.process(message, []) is False
    assert repository.routed is None
    assert repository.discarded is True
    assert message.status == MessageStatus.rejected
    assert message.filter_result["reasoning"] == "No locality was specified in the Red Alert notice"


def test_rejects_unreadable_ocr_with_an_image_specific_reason() -> None:
    repository = MagicMock()
    service = RedAlertAirViolationService(repository, lambda text: 36, lambda text, villages: None)
    message = SimpleNamespace(
        id=100,
        raw_text="redalert.com.lb OCR noise",
        raw_payload={"ocr_text": "OCR noise"},
        filter_result=None,
        status=MessageStatus.pending,
        error_message=None,
    )

    assert service.process(message, []) is False
    assert message.filter_result["reasoning"] == (
        "Location could not be identified reliably from the alert image"
    )


def _village(village_id: int, arabic: str, caza_en: str = "Sour") -> SimpleNamespace:
    return SimpleNamespace(
        id=village_id,
        ref_name_ar=arabic,
        acs_name=None,
        cad_name=None,
        caza_en=caza_en,
        caza_ar="صور",
    )


def test_parse_public_preview_preserves_text_link_and_image() -> None:
    html = """
    <div class="tgme_widget_message" data-post="redlinkleb/123">
      <time datetime="2026-08-20T08:30:00+00:00"></time>
      <div class="tgme_widget_message_text">تحليق طيران حربي فوق #الناقورة</div>
      <a class="tgme_widget_message_photo_wrap"
         style="background-image:url('https://example.test/photo.jpg')"></a>
    </div>
    """

    posts = parse_public_preview(html, "redlinkleb")

    assert len(posts) == 1
    assert posts[0].message_id == 123
    assert posts[0].text == "تحليق طيران حربي فوق #الناقورة"
    assert posts[0].link == "https://t.me/redlinkleb/123"
    assert posts[0].image_urls == ("https://example.test/photo.jpg",)
    assert posts[0].message_datetime.tzinfo == timezone.utc


def test_payload_uses_configured_channel() -> None:
    post = RedAlertPost(
        message_id=7,
        message_datetime=parse_public_preview(
            '<div class="tgme_widget_message" data-post="x/7">'
            '<time datetime="2026-08-20T08:30:00+00:00"></time></div>',
            "x",
        )[0].message_datetime,
        text="news",
        link="https://t.me/custom/7",
    )

    payload = post.raw_payload("custom")

    assert payload["external_message_id"] == "telegram:custom:7"
    assert payload["origin_account"] == "@custom"


def test_payload_preserves_collector_name() -> None:
    post = RedAlertPost(
        message_id=8,
        message_datetime=parse_public_preview(
            '<div class="tgme_widget_message" data-post="x/8">'
            '<time datetime="2026-08-20T08:30:00+00:00"></time></div>',
            "x",
        )[0].message_datetime,
        text="news",
        link="https://t.me/custom/8",
        collector="telegram_api",
    )

    payload = post.raw_payload("custom")

    assert payload["collector"] == "telegram_api"


def test_normalize_delivery_method_accepts_hyphenated_alias() -> None:
    assert RedAlertCollector._normalize_delivery_method("telegram-api") == "telegram_api"


def test_classifies_supported_air_violation_actions() -> None:
    assert classify_condition("تحليق طيران حربي فوق الناقورة") == 35
    assert classify_condition("طائرة استطلاع فوق صور") == 36
    assert classify_condition("مروحية فوق الجنوب") == 38
    assert classify_condition("خبر سياسي لا يتعلق بالطيران") is None


def test_rejects_end_of_day_statistics_as_news() -> None:
    text = """إحصاءات نهاية اليوم
إجمالي التنبيهات: 148
رصد المسيرات: 93
أكثر القرى رصداً (مسيرات): النبطية 21"""

    assert classify_condition(text) is None


def test_detects_image_post_preview_boilerplate() -> None:
    assert is_preview_boilerplate("🗺️ الخريطة 🤍 تبرّع الآن • 🚀 عزّز القناة <AM>")
    assert not is_preview_boilerplate("تحليق طيران حربي فوق الناقورة")


def test_matches_hashtag_village_and_ignores_action_hashtag() -> None:
    naqoura = _village(10, "الناقورة")

    matched = match_village("#طيران_حربي فوق #الناقورة", [naqoura])

    assert matched is not None
    assert matched[0].id == 10
    assert matched[1] == "الناقوره"


def test_matches_village_from_plain_text() -> None:
    mansouri = _village(11, "المنصوري")

    matched = match_village("غارات على بلدة المنصوري جنوب صور", [mansouri])

    assert matched is not None
    assert matched[0].id == 11


def test_does_not_turn_caza_label_into_an_arbitrary_village() -> None:
    nabatieh = _village(12, "النبطية", caza_en="Nabatieh")

    matched = match_village("مسيّرة Nabatieh", [nabatieh])

    assert matched is None


def test_detects_preview_boilerplate_with_changing_marker() -> None:
    assert is_preview_boilerplate("🗺️ الخريطة 🤍 تبرّع الآن • 🚀 عزّز القناة <JM>")


def test_does_not_fuzzy_match_unlisted_transliteration_variant() -> None:
    village = _village(13, "برج الشمالي", caza_en="Sour")
    village.acs_name = "Borj Ech-Chemali"

    matched = match_village("Al Shamali Hosh مسيرة", [village])

    assert matched is None


def test_matches_exact_english_village_name_from_whitelist() -> None:
    village = _village(14, "جرجوع", caza_en="Nabatiye")
    village.ref_name_en = "Jarjouaa"

    matched = match_village("Drone over Jarjouaa", [village])

    assert matched is not None
    assert matched[0].id == 14


def _post(message_id: int, when: datetime) -> RedAlertPost:
    return RedAlertPost(
        message_id=message_id,
        message_datetime=when,
        text="تحليق",
        link=f"https://t.me/redlinkleb/{message_id}",
    )


def test_fetch_limit_for_hours_is_capped() -> None:
    assert fetch_limit_for_hours(1, 20) == 40
    assert fetch_limit_for_hours(1, 50) == 50
    assert fetch_limit_for_hours(6, 20) == HOURS_FETCH_LIMIT_CAP
    assert fetch_limit_for_hours(100, 20) == HOURS_FETCH_LIMIT_CAP


def test_posts_within_window_excludes_older_posts() -> None:
    cutoff = datetime(2026, 8, 24, 6, 0, tzinfo=timezone.utc)
    inside = _post(1, datetime(2026, 8, 24, 7, 0, tzinfo=timezone.utc))
    boundary = _post(2, cutoff)
    outside = _post(3, datetime(2026, 8, 24, 5, 59, tzinfo=timezone.utc))

    assert posts_within_window([inside, boundary, outside], cutoff) == [inside, boundary]
    assert posts_within_window([inside, outside], None) == [inside, outside]


def _collector_post(message_id: int = 501) -> RedAlertPost:
    when = datetime(2026, 8, 24, 8, 0, tzinfo=timezone.utc)
    return RedAlertPost(
        message_id=message_id,
        message_datetime=when,
        text="تحليق طيران حربي فوق #الجنوب",
        link=f"https://t.me/redlinkleb/{message_id}",
    )


def test_collect_once_counts_air_violation_only_when_route_writes() -> None:
    db = MagicMock()
    db.scalar.return_value = None

    air_service = MagicMock()
    air_service.process.return_value = True

    collector = RedAlertCollector(db, air_violation_service=air_service)
    collector._ensure_source = MagicMock(return_value=SimpleNamespace(id=78))
    collector._ensure_unclassified_air_condition = MagicMock()
    collector._fetch_posts = MagicMock(return_value=[_collector_post()])
    collector._text_with_optional_ocr = MagicMock(side_effect=lambda post: post.text)

    result = collector.collect_once()

    assert result["air_violations"] == 1
    assert result["saved"] == 1
    air_service.process.assert_called_once()


def test_collect_once_reports_zero_air_violations_for_duplicate_only_run() -> None:
    existing = SimpleNamespace(
        id=1,
        status=MessageStatus.routed_air_violation,
        raw_payload={},
        raw_text="تحليق طيران حربي فوق #الجنوب",
    )
    db = MagicMock()
    db.scalar.return_value = existing

    air_service = MagicMock()
    collector = RedAlertCollector(db, air_violation_service=air_service)
    collector._ensure_source = MagicMock(return_value=SimpleNamespace(id=78))
    collector._ensure_unclassified_air_condition = MagicMock()
    collector._fetch_posts = MagicMock(return_value=[_collector_post()])
    collector._enrich_existing_with_ocr = MagicMock(return_value=False)

    result = collector.collect_once()

    assert result["air_violations"] == 0
    assert result["duplicates"] == 1
    air_service.process.assert_not_called()


def test_process_persists_air_violation_row_and_routed_status() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for air-violation routing coverage.")

    engine = create_engine(database_url)
    try:
        connection = engine.connect()
    except OperationalError as exc:
        pytest.skip(f"Database is unavailable: {exc}")

    transaction = connection.begin()
    db = Session(bind=connection, join_transaction_mode="create_savepoint")
    marker = uuid4().hex
    try:
        has_routed_status = db.scalar(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_enum e
                    JOIN pg_type t ON e.enumtypid = t.oid
                    WHERE t.typname = 'message_status'
                      AND e.enumlabel = 'routed_air_violation'
                )
                """
            )
        )
        if not has_routed_status:
            pytest.skip(
                "Migration 20260824_0033 must be applied before air-violation "
                "routing integration coverage."
            )

        source = Source(
            type=SourceType.telegram,
            name="Red Alert Lebanon",
            external_id=f"red-alert-test-{marker}",
            config={},
        )
        db.add(source)
        db.flush()

        message = RawMessage(
            source_id=source.id,
            external_message_id=f"telegram:redlinkleb:{marker}",
            source_platform="telegram",
            source_name="Red Alert Lebanon",
            origin_account="@redlinkleb",
            raw_text="تحليق طيران حربي فوق #الجنوب",
            raw_payload={"source_link": f"https://t.me/redlinkleb/{marker}"},
            message_datetime=datetime(2026, 8, 24, 8, 0, tzinfo=timezone.utc),
            status=MessageStatus.pending,
        )
        db.add(message)
        db.flush()
        message_id = message.id

        service = RedAlertAirViolationService(
            AirViolationRepository(db),
            classify_condition,
            match_village,
        )
        wrote = service.process(message, [])

        assert wrote is True
        assert message.status == MessageStatus.routed_air_violation
        assert message.status != MessageStatus.error
        row_count = db.scalar(
            select(func.count())
            .select_from(AirViolation)
            .where(AirViolation.raw_message_id == message_id)
        )
        assert row_count == 1
    except (OperationalError, ProgrammingError) as exc:
        pytest.skip(f"Air-violation routing schema is unavailable: {exc}")
    finally:
        db.close()
        transaction.rollback()
        connection.close()
