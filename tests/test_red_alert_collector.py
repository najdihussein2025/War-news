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
    RED_ZONE_OCR_MARKER,
    RedAlertPost,
    RedAlertCollector,
    aircraft_term_conflict,
    classify_condition,
    fetch_limit_for_hours,
    is_preview_boilerplate,
    match_village,
    match_villages,
    parse_public_preview,
    posts_within_window,
)
from app.core.scripts.run_red_alert_collector import collector_kwargs_for_hours
from app.news.models import MessageStatus, RawMessage, Village
from app.news.models.air_violation import AirViolation
from app.news.services.air_violations.air_violation_eligibility import evaluate_air_violation_text
from app.news.repositories.air_violation_repository import AirViolationRepository
from app.news.services.air_violations.red_alert_air_violation_service import RedAlertAirViolationService
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


def test_kinetic_red_alert_reenters_incident_pipeline() -> None:
    repository = MagicMock()
    service = RedAlertAirViolationService(
        repository, lambda text: 38, lambda text, villages: None
    )
    message = SimpleNamespace(
        id=199,
        raw_text="نجاة مسعفين من غارة نفذتها مروحية أباتشي في ميفدون",
        raw_payload={},
        filter_result=None,
        match_result=None,
        status=MessageStatus.pending,
        error_message=None,
    )

    assert service.process(message, []) is False
    # 'parsed', not 'pending': the audit fills filter_result, and the relevance
    # stage only claims pending rows with filter_result IS NULL, so a pending
    # row would be claimed by no pipeline stage at all.
    assert message.status == MessageStatus.parsed
    assert message.filter_result["air_violation_rerouted"]["matched_terms"]
    repository.route_from_match.assert_not_called()


def test_kinetic_red_alert_does_not_reopen_materialized_message() -> None:
    repository = MagicMock()
    service = RedAlertAirViolationService(
        repository, lambda text: 38, lambda text, villages: None
    )
    message = SimpleNamespace(
        id=200,
        raw_text="طائرة مسيرة استهدفت سيارة في النبطية",
        raw_payload={},
        filter_result=None,
        match_result=None,
        status=MessageStatus.materialized,
        error_message=None,
    )

    assert service.process(message, []) is False
    assert message.status == MessageStatus.materialized


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


def test_routes_caza_only_air_violation_without_fake_village() -> None:
    class _AirViolationRepository:
        routed = None

        def route_from_match(self, message, result) -> bool:
            self.routed = (message, result)
            return True

        def discard_for_message(self, message) -> None:
            raise AssertionError("caza-only air violations should not be discarded")

    repository = _AirViolationRepository()
    service = RedAlertAirViolationService(
        repository,  # type: ignore[arg-type]
        lambda text: 35,
        lambda text, villages: None,
    )
    message = SimpleNamespace(
        id=101,
        raw_text="#مقاتلات_حربية #البقاع",
        raw_payload={},
        filter_result=None,
        match_result=None,
        status=MessageStatus.pending,
        error_message=None,
    )
    village = _village(20, "طيبة بعلبك", caza_en="West Bekaa")
    village.caza_ar = "البقاع الغربي"

    assert service.process(message, [village]) is True
    assert repository.routed is not None
    assert message.status == MessageStatus.routed_air_violation
    assert message.filter_result["reasoning"] == (
        "Supported air-violation keyword and caza matched"
    )
    routed_result = repository.routed[1]
    assert routed_result.village_matches == []


def test_routes_south_region_air_violation_without_fake_village() -> None:
    repository = MagicMock()
    repository.route_from_match.return_value = True
    service = RedAlertAirViolationService(repository, lambda text: 35, lambda text, villages: None)
    message = SimpleNamespace(
        id=102,
        raw_text="#مقاتلات_حربية #الجنوب",
        raw_payload={},
        filter_result=None,
        match_result=None,
        status=MessageStatus.pending,
        error_message=None,
    )

    assert service.process(message, []) is True
    repository.discard_for_message.assert_not_called()
    repository.route_from_match.assert_called_once()


def test_routes_lebanon_region_air_violation_as_multiple_regions() -> None:
    repository = MagicMock()
    repository.route_from_match.return_value = True
    service = RedAlertAirViolationService(repository, lambda text: 35, lambda text, villages: None)
    message = SimpleNamespace(
        id=103,
        raw_text="#\u0645\u0642\u0627\u062a\u0644\u0627\u062a_\u062d\u0631\u0628\u064a\u0629 #\u0644\u0628\u0646\u0627\u0646",
        raw_payload={},
        filter_result=None,
        match_result=None,
        status=MessageStatus.pending,
        error_message=None,
    )

    assert service.process(message, []) is True
    routed_result = repository.route_from_match.call_args.args[1]

    assert routed_result.village_matches == []
    assert routed_result.raw_condition_text == "#\u0645\u0642\u0627\u062a\u0644\u0627\u062a_\u062d\u0631\u0628\u064a\u0629 #\u0644\u0628\u0646\u0627\u0646"


def test_red_alert_air_violation_routes_all_exact_villages_from_ocr_text() -> None:
    repository = MagicMock()
    repository.route_from_match.return_value = True
    service = RedAlertAirViolationService(repository, lambda text: 36, lambda text, villages: None)
    chiyah = _village(201, "شياح", caza_en="Baabda")
    chiyah.ref_name_en = "Chiyah"
    ghobeiry = _village(202, "الغبيري", caza_en="Baabda")
    ghobeiry.ref_name_en = "Ghobeiry"
    haret_hreik = _village(203, "حارة حريك", caza_en="Baabda")
    haret_hreik.ref_name_en = "Haret Hreik"
    message = SimpleNamespace(
        id=104,
        raw_text=(
            "V7 |RED redalert.com.lb Ghobeiry حارة حريك حيطة وحذر "
            "__RED_ZONE_TEXT__ Chiyah Ghobeiry Haret Hreik طيران استطلاعي"
        ),
        raw_payload={"ocr_text": "Ghobeiry Haret Hreik Chiyah"},
        filter_result=None,
        match_result=None,
        status=MessageStatus.pending,
        error_message=None,
    )

    assert service.process(message, [chiyah, ghobeiry, haret_hreik]) is True
    routed_result = repository.route_from_match.call_args.args[1]

    assert {match.matched_village_id for match in routed_result.village_matches} == {
        201,
        202,
        203,
    }


def test_red_alert_air_violation_routes_all_alias_villages_from_ocr_text() -> None:
    repository = MagicMock()
    repository.route_from_match.return_value = True
    service = RedAlertAirViolationService(repository, lambda text: 36, match_village, match_villages)
    aain_et_tine = _village(203, "\u0639\u064a\u0646 \u0627\u0644\u062a\u064a\u0646\u0629 \u0628\u0642\u0627\u0639 \u0627\u0644\u063a\u0631\u0628\u064a", caza_en="West Bekaa")
    aain_et_tine.ref_name_en = "Aain Et-Tine BG"
    aain_et_tine.acs_code = 52116
    libbaya = _village(204, "\u0644\u0628\u0627\u064a\u0627", caza_en="West Bekaa")
    libbaya.ref_name_en = "Libbaya BG"
    libbaya.acs_code = 52274
    sohmor = _village(205, "\u0633\u062d\u0645\u0631", caza_en="West Bekaa")
    sohmor.ref_name_en = "Sohmor"
    sohmor.acs_code = 52267
    yohmor = _village(206, "\u064a\u062d\u0645\u0631 \u0628\u0642\u0627\u0639 \u0627\u0644\u063a\u0631\u0628\u064a", caza_en="West Bekaa")
    yohmor.ref_name_en = "Yohmor BG"
    yohmor.acs_code = 52281
    machghara = _village(207, "\u0645\u0634\u063a\u0631\u0629", caza_en="West Bekaa")
    machghara.ref_name_en = "Machghara"
    machghara.acs_code = 52111
    qaraaoun = _village(208, "\u0627\u0644\u0642\u0631\u0639\u0648\u0646", caza_en="West Bekaa")
    qaraaoun.ref_name_en = "Qaraaoun"
    qaraaoun.acs_code = 52237
    message = SimpleNamespace(
        id=105,
        raw_text=(
            f"redalert.com.lb \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631 {RED_ZONE_OCR_MARKER} "
            "Qaraoun Machghara Sohmor Ain El Tineh Libbaya \u0645\u0633\u064a\u0631\u0629"
        ),
        raw_payload={"ocr_text": "Qaraoun Machghara Sohmor Ain El Tineh Libbaya"},
        filter_result=None,
        match_result=None,
        status=MessageStatus.pending,
        error_message=None,
    )

    assert service.process(
        message,
        [aain_et_tine, libbaya, sohmor, yohmor, machghara, qaraaoun],
    ) is True
    routed_result = repository.route_from_match.call_args.args[1]

    assert {match.matched_village_id for match in routed_result.village_matches} == {
        203,
        204,
        205,
        207,
        208,
    }


def test_red_alert_ocr_red_zone_aliases_do_not_add_generic_village_noise() -> None:
    repository = MagicMock()
    repository.route_from_match.return_value = True
    service = RedAlertAirViolationService(repository, lambda text: 36, match_village, match_villages)
    froun = _village(301, "\u0641\u0631\u0648\u0646", caza_en="Bint Jubail")
    froun.ref_name_en = "Froun"
    froun.acs_code = 72276
    qsair_aakkar = _village(302, "\u0627\u0644\u0642\u0635\u064a\u0631", caza_en="Akkar")
    qsair_aakkar.ref_name_en = "Qsair Aakkar"
    qsair_aakkar.acs_code = 35415
    message = SimpleNamespace(
        id=106,
        raw_text=(
            f"redalert.com.lb \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631 "
            f"{RED_ZONE_OCR_MARKER} \u0641\u0631\u0648\u0646 \u0627\u0644\u0642\u0635\u064a\u0631"
        ),
        raw_payload={"ocr_text": "\u0641\u0631\u0648\u0646 \u0627\u0644\u0642\u0635\u064a\u0631"},
        filter_result=None,
        match_result=None,
        status=MessageStatus.pending,
        error_message=None,
    )

    assert service.process(message, [froun, qsair_aakkar]) is True
    routed_result = repository.route_from_match.call_args.args[1]

    assert [match.matched_village_id for match in routed_result.village_matches] == [301]


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
    assert classify_condition("مروحية تحلق فوق الجنوب") == 38
    assert classify_condition("خبر سياسي لا يتعلق بالطيران") is None


@pytest.mark.parametrize(
    "term",
    [
        "طيران مسير",
        "طيران مسيّر",
        "مسيرة",
        "مسيّرة",
        "مسيّر",
        "مسيرات",
        "درون",
        "drone",
        "UAV",
        "طائرة مسيرة",
        "محلقة",
    ],
)
def test_every_drone_variant_is_surveillance(term: str) -> None:
    assert classify_condition(f"{term} فوق صور") == 36


@pytest.mark.parametrize(
    "text",
    [
        "مروحي إسرائيلي فوق صور",
        "مروحية فوق صور",
        "مروحيه فوق صور",
        "مروحيات معادية في الجنوب",
        "طيران مروحي في الجنوب",
        "اباتشي تحلق فوق الناقورة",
        "أباتشي فوق الناقورة",
        "هليكوبتر اسرائيلية",
        "هليكوبتير فوق الخيام",
        "helicopter over Tyre",
        "Apache over Naqoura",
        "كوترية فوق صور",
    ],
)
def test_every_helicopter_spelling_is_helicopter_without_hover_verb(text: str) -> None:
    assert classify_condition(text) == 38


def test_drone_text_with_hover_verb_is_never_helicopter() -> None:
    assert classify_condition("مسيرة معادية تحلق فوق بنت جبيل") == 36


def test_aircraft_without_a_helicopter_word_is_not_helicopter() -> None:
    assert classify_condition("طائرة تحلق فوق صور") != 38


def test_text_with_helicopter_and_drone_words_is_drone_with_both_term_sets_recorded() -> None:
    text = "مروحية ومسيرة معادية تحلقان فوق صور"

    assert classify_condition(text) == 36
    conflict = aircraft_term_conflict(text)
    assert conflict is not None
    assert "مروحيه" in conflict["helicopter_terms"]
    assert "مسيره" in conflict["drone_terms"]
    assert aircraft_term_conflict("مروحية تحلق فوق صور") is None


def test_apache_strike_is_helicopter_by_keyword_but_rejected_as_incident() -> None:
    text = "مروحية أباتشي استهدفت مبنى في ميفدون"

    assert classify_condition(text) == 38
    assert evaluate_air_violation_text(text).eligible is False
    assert evaluate_air_violation_text(text).belongs_in_incidents is True


def test_ordinary_warplane_overflight_is_warplane() -> None:
    assert classify_condition("تحليق طيران حربي فوق الناقورة") == 35


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


def test_focused_red_zone_ocr_with_multiple_villages_is_not_single_place() -> None:
    arnoun = _village(15, "أرنون", caza_en="Nabatiye")
    mayfadoun = _village(16, "ميفدون", caza_en="Nabatiye")

    matched = match_village(
        f"map labels outside circle {RED_ZONE_OCR_MARKER} أرنون ميفدون",
        [arnoun, mayfadoun],
    )

    assert matched is None


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


def test_matches_red_alert_ocr_aliases_from_rejected_maps() -> None:
    taibeh = _village(21, "طيبة مرجعيون", caza_en="Marjaayoun")
    taibeh.acs_code = 73232
    shamali = _village(22, "برج الشمالي", caza_en="Sour")
    shamali.acs_code = 62128

    matched_taibeh = match_village(f"noise {RED_ZONE_OCR_MARKER} Et Taibeh مسيرة", [taibeh, shamali])
    matched_shamali = match_village(f"noise {RED_ZONE_OCR_MARKER} Burj Al Shar مسيرة", [taibeh, shamali])

    assert matched_taibeh is not None
    assert matched_taibeh[0].id == 21
    assert matched_shamali is not None
    assert matched_shamali[0].id == 22


def test_matches_red_alert_zibqine_ocr_alias_to_sour_village() -> None:
    zibqine = _village(24, "\u0632\u0628\u0642\u064a\u0646", caza_en="Sour")
    zibqine.ref_name_en = "Zibqine"
    zibqine.acs_code = 62286

    matched = match_village(
        f"noise {RED_ZONE_OCR_MARKER} Zibqine \u0645\u0633\u064a\u0631\u0629",
        [zibqine],
    )

    assert matched is not None
    assert matched[0].id == 24
    assert matched[0].caza_en == "Sour"


def test_matches_red_alert_maarakeh_alias_to_sour_village() -> None:
    maarake = _village(25, "\u0645\u0639\u0631\u0643\u0629", caza_en="Sour")
    maarake.ref_name_en = "Maarake"
    maarake.acs_code = 62231

    matched = match_village("Drone over Maarakeh", [maarake])

    assert matched is not None
    assert matched[0].id == 25
    assert matched[0].caza_en == "Sour"


def test_telegram_text_location_wins_over_conflicting_ocr_location() -> None:
    repository = MagicMock()
    repository.route_from_match.return_value = True
    service = RedAlertAirViolationService(repository, lambda text: 36, match_village, match_villages)
    maarake = _village(26, "\u0645\u0639\u0631\u0643\u0629", caza_en="Sour")
    maarake.ref_name_en = "Maarake"
    maarake.acs_code = 62231
    saida = _village(27, "\u0635\u064a\u062f\u0627", caza_en="Saida")
    saida.ref_name_en = "Saida"
    message = SimpleNamespace(
        id=106,
        raw_text=(
            "Drone over Maarakeh\n"
            f"{RED_ZONE_OCR_MARKER} Saida \u0645\u0633\u064a\u0631\u0629"
        ),
        raw_payload={
            "preview_text": "Drone over Maarakeh",
            "ocr_text": f"{RED_ZONE_OCR_MARKER} Saida \u0645\u0633\u064a\u0631\u0629",
        },
        filter_result=None,
        match_result=None,
        status=MessageStatus.pending,
        error_message=None,
    )

    assert service.process(message, [maarake, saida]) is True
    routed_result = repository.route_from_match.call_args.args[1]

    assert [match.matched_village_id for match in routed_result.village_matches] == [26]


def _alias_village(village_id: int, acs_code: int) -> SimpleNamespace:
    village = _village(village_id, "", caza_en="West Bekaa")
    village.acs_code = acs_code
    return village


def test_red_zone_latin_crop_matches_every_alias_word_sequence() -> None:
    villages = [
        _alias_village(1, 52237),  # Qaraoun
        _alias_village(2, 52111),  # Machghara
        _alias_village(3, 52267),  # Sohmor
        _alias_village(4, 52116),  # Ain El Tineh
        _alias_village(5, 52274),  # Libbaya
    ]

    matched = match_villages(
        f"noise {RED_ZONE_OCR_MARKER} Qaraoun Machghara Sohmor Ain El Tineh Libbaya",
        villages,
    )

    assert {village.id for village, _alias in matched} == {1, 2, 3, 4, 5}


def test_red_zone_latin_alias_does_not_match_inside_a_longer_word() -> None:
    villages = [_alias_village(3, 52267), _alias_village(5, 52274)]

    matched = match_villages(f"noise {RED_ZONE_OCR_MARKER} Xsohmor Libbayaki", villages)

    assert matched == []


def test_short_latin_alias_matches_only_as_a_whole_word(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.sources.services import red_alert_collector

    monkeypatch.setitem(red_alert_collector.RED_ALERT_VILLAGE_ALIASES, "tyr", 99001)
    village = _alias_village(9, 99001)

    whole = match_villages(f"noise {RED_ZONE_OCR_MARKER} Tyr", [village])
    inside = match_villages(f"noise {RED_ZONE_OCR_MARKER} Tyrsana Katyr", [village])

    assert [item.id for item, _alias in whole] == [9]
    assert inside == []


def _red_zone_message(message_id: int, outside: str, crop: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=message_id,
        raw_text=f"redalert.com.lb {outside} حيطة وحذر {RED_ZONE_OCR_MARKER} {crop}",
        raw_payload={"ocr_text": crop},
        filter_result=None,
        match_result=None,
        status=MessageStatus.pending,
        error_message=None,
    )


def test_red_zone_canonical_name_outside_the_crop_does_not_match() -> None:
    repository = MagicMock()
    service = RedAlertAirViolationService(repository, lambda text: 36, match_village, match_villages)
    ghobeiry = _village(401, "الغبيري", caza_en="Baabda")
    ghobeiry.ref_name_en = "Ghobeiry"

    assert service.process(_red_zone_message(107, "Ghobeiry", "unreadable crop 59"), [ghobeiry]) is False
    repository.route_from_match.assert_not_called()


def test_red_zone_canonical_name_shared_by_two_villages_is_left_unmatched() -> None:
    repository = MagicMock()
    service = RedAlertAirViolationService(repository, lambda text: 36, match_village, match_villages)
    zebdine_nabatiye = _village(402, "زبدين", caza_en="Nabatiye")
    zebdine_nabatiye.ref_name_en = "Zebdine"
    zebdine_marjaayoun = _village(403, "زبدين", caza_en="Marjaayoun")
    zebdine_marjaayoun.ref_name_en = "Zebdine"
    message = _red_zone_message(108, "", "Zebdine")

    assert service.process(message, [zebdine_nabatiye, zebdine_marjaayoun]) is False
    repository.route_from_match.assert_not_called()
    assert message.status == MessageStatus.rejected


def test_red_zone_rejects_surveillance_villages_from_different_cazas() -> None:
    repository = MagicMock()
    repository.route_from_match.return_value = True
    service = RedAlertAirViolationService(repository, lambda text: 36, match_village, match_villages)
    sohmor = _village(404, "سحمر", caza_en="West Bekaa")
    sohmor.acs_code = 52267  # listed by alias only
    chiyah = _village(405, "شياح", caza_en="Baabda")
    chiyah.ref_name_en = "Chiyah"  # no alias; canonical name only

    message = _red_zone_message(109, "", "Sohmor Chiyah")

    assert service.process(message, [sohmor, chiyah]) is False
    repository.route_from_match.assert_not_called()
    assert message.filter_result["reasoning"] == "Surveillance locations span multiple cazas"


def test_red_zone_ocr_ignores_alias_outside_the_red_zone_crop() -> None:
    # Map labels outside the red zone are nearby places, not affected villages,
    # so an unreadable crop must not fall back to aliases in the full OCR text.
    shamali = _village(23, "برج الشمالي", caza_en="Sour")
    shamali.acs_code = 62128
    text = f"redalert.com.lb Burj Al Shar مسيرة {RED_ZONE_OCR_MARKER} unreadable crop 59"

    assert match_village(text, [shamali]) is None
    assert match_villages(text, [shamali]) == []


def _post(message_id: int, when: datetime) -> RedAlertPost:
    return RedAlertPost(
        message_id=message_id,
        message_datetime=when,
        text="تحليق",
        link=f"https://t.me/redlinkleb/{message_id}",
    )


def test_fetch_limit_for_hours_is_capped() -> None:
    assert fetch_limit_for_hours(1, 20) == 60
    assert fetch_limit_for_hours(1, 50) == 60
    assert fetch_limit_for_hours(20, 20) == HOURS_FETCH_LIMIT_CAP
    assert fetch_limit_for_hours(100, 20) == HOURS_FETCH_LIMIT_CAP


def test_default_red_alert_collection_window_starts_at_beirut_midnight() -> None:
    now = datetime(2026, 9, 24, 8, 35, tzinfo=timezone.utc)

    kwargs = collector_kwargs_for_hours(None, now=now)

    assert kwargs["min_message_datetime"] == datetime(2026, 9, 23, 21, 0, tzinfo=timezone.utc)
    assert kwargs["fetch_limit"] == fetch_limit_for_hours(12, 20)


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
        village = Village(
            acs_code=int(marker[:7], 16),
            ref_name_en=f"Air Village {marker}",
            ref_name_ar=f"Air Village {marker}",
            caza_en="Test Caza",
            caza_ar="Test Caza",
        )
        db.add(village)
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
            lambda text, villages: (village, village.ref_name_en or ""),
        )
        wrote = service.process(message, [village])

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


def test_helicopter_terminology_matches_collector_keywords() -> None:
    from app.sources.services.red_alert_collector import AIR_KEYWORDS, HELICOPTER_KEYWORDS, normalize_arabic

    yaml_terms = {
        normalize_arabic(term)
        for condition_id, terms in AIR_KEYWORDS
        if condition_id == 38
        for term in terms
    }
    expected = {normalize_arabic(term) for term in HELICOPTER_KEYWORDS}

    assert expected <= yaml_terms
