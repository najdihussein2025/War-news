from datetime import datetime, timezone
from types import SimpleNamespace

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
from app.news.models import MessageStatus
from app.news.services.red_alert_air_violation_service import RedAlertAirViolationService


def test_rejects_air_violation_without_a_canonical_village() -> None:
    class _AirViolationRepository:
        routed = None

        def route_from_match(self, message, result) -> None:
            self.routed = (message, result)

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
        filter_result=None,
        match_result=None,
        status=MessageStatus.pending,
        error_message=None,
    )

    assert service.process(message, []) is False
    assert repository.routed is None
    assert repository.discarded is True
    assert message.status == MessageStatus.rejected
    assert message.filter_result["reasoning"] == "No canonical village matched"


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
