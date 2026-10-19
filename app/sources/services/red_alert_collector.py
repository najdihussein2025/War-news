from __future__ import annotations

import asyncio
import io
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.llm_knowledge.loader import load_terminology
from app.news.models import Condition, MessageStatus, RawMessage, Village
from app.news.repositories.air_violation_repository import AirViolationRepository
from app.news.services.air_violations.latin_location_words import (
    latin_location_words,
    latin_name_in_words,
    normalize_latin_location_token,
)
from app.news.services.air_violations.red_alert_air_violation_service import RedAlertAirViolationService
from app.sources.actions.ingest_source_action import IngestSourceAction
from app.sources.models import Source, SourceType

logger = logging.getLogger(__name__)

SOURCE_EXTERNAL_ID = "red_alert_telegram"
SOURCE_NAME = "Red Alert Lebanon"
UNCLASSIFIED_AIR_CONDITION_ID = 45
OCR_VERSION = 3
RED_ZONE_OCR_MARKER = "__RED_ZONE_TEXT__"
BEIRUT_TIMEZONE = ZoneInfo("Asia/Beirut")
# Exact labels used by the Red Alert map, mapped to canonical Villages.json
# ACS codes. These are spelling aliases only; they never select a nearby place.
# Intentionally code-only / ingestion-scoped (Phase 2.5 clarification #5).
RED_ALERT_VILLAGE_ALIASES: dict[str, int] = {
    "beirut": 10999,
    "burj el brajne": 21177,
    "علي الطاهر": 71115,
    "برج الشمالي": 62128,
    "لمنصوريى": 62296,
    "عين بعال": 62243,
    "وادي حيلو": 62218,
    "دى حيلو": 62218,
    "shahim": 23211,
    "al bazuriya": 62246,
    "al bazuriye": 62246,
    "burj al shar": 62128,
    "burj al shamali": 62128,
    "et taibeh": 73232,
    "\u0628\u0631\u062c \u0642\u0644\u0648\u064a\u0647": 72264,
    "\u0628\u0631\u062c \u0642\u0644\u0648\u064a\u0629": 72264,
    "borj qalaouiye": 72264,
    "bourj qalaouiye": 72264,
    "\u0641\u0631\u0648\u0646": 72276,
    "froun": 72276,
    "\u0639\u0644\u0645\u0627\u0646\u0629": 73293,
    "aalmane marjaayoun": 73293,
    "aalmane": 73293,
    "\u0627\u0644\u063a\u0646\u062f\u0648\u0631\u064a\u0629": 72274,
    "\u063a\u0646\u062f\u0648\u0631\u064a\u0629": 72274,
    "ghandouriyet bent jbayl": 72274,
    "ghandouriyeh": 72274,
    "\u0635\u0631\u0628\u064a\u0646": 72267,
    "srobbine": 72267,
    "sarbine": 72267,
    "\u064a\u0627\u0637\u0631": 72277,
    "yater": 72277,
    "\u0634\u0645\u0639": 62298,
    "chamaa": 62298,
    "\u0644\u0628\u0627\u064a\u0627": 52274,
    "libbaya": 52274,
    "lebbaya": 52274,
    "\u0639\u064a\u0646 \u0627\u0644\u062a\u064a\u0646\u0629": 52116,
    "\u0639\u064a\u0646 \u0627\u0644\u062a\u064a\u0646\u0629 \u0628\u0642\u0627\u0639 \u0627\u0644\u063a\u0631\u0628\u064a": 52116,
    "aain et tine": 52116,
    "ain et tine": 52116,
    "ain el tine": 52116,
    "ain el tineh": 52116,
    "\u0643\u0627\u0645\u062f \u0627\u0644\u0644\u0648\u0632": 52217,
    "kamed el laouz": 52217,
    "kamed el-laouz": 52217,
    "kamed laouz": 52217,
    "\u0645\u0634\u063a\u0631\u0629": 52111,
    "machghara": 52111,
    "\u0633\u062d\u0645\u0631": 52267,
    "sohmor": 52267,
    "\u064a\u062d\u0645\u0631": 52281,
    "\u064a\u062d\u0645\u0631 \u0628\u0642\u0627\u0639 \u0627\u0644\u063a\u0631\u0628\u064a": 52281,
    "yohmor": 52281,
    "yohmor bg": 52281,
    "\u0627\u0644\u0642\u0631\u0639\u0648\u0646": 52237,
    "\u0642\u0631\u0639\u0648\u0646": 52237,
    "qaraaoun": 52237,
    "qaraoun": 52237,
    "\u0632\u0628\u062f\u064a\u0646": 71122,
    "\u0632\u0628\u062f\u064a\u0646 \u0627\u0644\u0646\u0628\u0637\u064a\u0629": 71122,
    "zibdine": 71122,
    "zebdine": 71122,
    "zibdin": 71122,
    "zebdin": 71122,
    "\u0645\u064a\u0641\u062f\u0648\u0646": 71344,
    "mayfadoun": 71344,
    "\u0632\u0628\u0642\u064a\u0646": 62286,
    "zibqine": 62286,
    "zebqine": 62286,
    "zibqin": 62286,
    "zebqin": 62286,
    "maarakeh": 62231,
    "maarakah": 62231,
    "maarake": 62231,
    "\u0643\u0641\u0631 \u062a\u0628\u0646\u064a\u062a": 71166,
    "kfar tibnit": 71166,
    "\u062d\u0631\u0648\u0641": 71331,
    "harouf en-nabatiyeh": 71331,
    "harouf": 71331,
    "\u0642\u0644\u064a\u0644\u0629": 62287,
    "\u0627\u0644\u0642\u0644\u064a\u0644\u0629": 62287,
    "qlaile": 62287,
    "qlaile sour": 62287,
    "\u0627\u0644\u0645\u0646\u0635\u0648\u0631\u064a": 62296,
    "mansouri sour": 62296,
    "\u0637\u064a\u0628\u0629 \u0645\u0631\u062c\u0639\u064a\u0648\u0646": 73232,
    "taybet matjaayoun": 73232,
    "taybet marjaayoun": 73232,
    "\u0643\u0641\u0631\u0643\u064a\u0644\u0627": 73159,
    "\u0643\u0641\u0631 \u0643\u064a\u0644\u0627": 73159,
    "kfar kila": 73159,
    "\u0642\u0639\u0642\u0639\u064a\u0629 \u0627\u0644\u062c\u0633\u0631": 71381,
    "qaaqaaiyet ej-jisr": 71381,
    "\u0632\u0648\u0637\u0631 \u0627\u0644\u0634\u0631\u0642\u064a\u0629": 71367,
    "zaoutar ech-charqiye": 71367,
    "\u0632\u0648\u0637\u0631 \u0627\u0644\u063a\u0631\u0628\u064a\u0629": 71364,
    "zaoutar el-gharbiye": 71364,
    "\u0635\u064a\u0631 \u0627\u0644\u063a\u0631\u0628\u064a\u0629": 71397,
    "\u064a\u0633\u064a\u0631 \u0627\u0644\u063a\u0631\u0628\u064a\u0629": 71397,
    "sir el-gharbiye": 71397,
    "\u0645\u062c\u062f\u0644 \u0633\u0644\u0645": 73279,
    "majdel selm": 73279,
    "\u062f\u064a\u0631 \u0642\u0627\u0646\u0648\u0646 \u0627\u0644\u0646\u0647\u0631": 62263,
    "deir qanoun en-nahr": 62263,
    "\u0635\u0648\u0627\u0646\u0629": 26220,
    "souanet jbayl": 26220,
}

BROKEN_RED_ALERT_MAP_FALLBACKS: dict[tuple[int, int], str] = {
    (7, 26): "Zibdine En-Nabatiyeh \u0632\u0628\u062f\u064a\u0646 \u0627\u0644\u0646\u0628\u0637\u064a\u0629 \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
    (8, 11): "Zebqine \u0632\u0628\u0642\u064a\u0646 \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
    (9, 23): "Borj qalaouiye \u0628\u0631\u062c \u0642\u0644\u0648\u064a\u0647 \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
}

BROKEN_RED_ALERT_MESSAGE_FALLBACKS: dict[int, str] = {
    45668: "Zebqine \u0632\u0628\u0642\u064a\u0646 \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
    45673: "Aalmane Marjaayoun \u0639\u0644\u0645\u0627\u0646\u0629 Aadchit Ech-Chqif \u0639\u062f\u0634\u064a\u062a \u0627\u0644\u0634\u0642\u064a\u0641 \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
    45674: "Aadchit Ech-Chqif \u0639\u062f\u0634\u064a\u062a \u0627\u0644\u0634\u0642\u064a\u0641 Aalma Ech-Chaab \u0639\u0644\u0645\u0627 \u0627\u0644\u0634\u0639\u0628 Jbal El-Botm \u062c\u0628\u0627\u0644 \u0627\u0644\u0628\u0637\u0645 Yater \u064a\u0627\u0637\u0631 \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
    45675: "\u0641\u0631\u0648\u0646 \u0627\u0644\u063a\u0646\u062f\u0648\u0631\u064a\u0629 \u0637\u0648\u064a\u0631\u064a \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
    45683: "Lala \u0644\u0627\u0644\u0627 Yohmor BG \u064a\u062d\u0645\u0631 \u0628\u0642\u0627\u0639 \u0627\u0644\u063a\u0631\u0628\u064a \u0645\u0633\u064a\u0631\u0629 \u0623\u0642\u0635\u0649 \u062f\u0631\u062c\u0627\u062a \u0627\u0644\u062d\u0630\u0631",
    45685: "\u062d\u0631\u0628\u064a \u0628\u0642\u0627\u0639 \u063a\u0631\u0628\u064a",
    45692: "\u0641\u0631\u0648\u0646 \u063a\u0646\u062f\u0648\u0631\u064a\u0629 \u0628\u0646\u062a \u062c\u0628\u064a\u0644 \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
    45693: "\u0627\u0644\u0645\u0646\u0635\u0648\u0631\u064a Mansouri Sour \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
    45694: "Jbal El-Botm \u062c\u0628\u0627\u0644 \u0627\u0644\u0628\u0637\u0645 Yater \u064a\u0627\u0637\u0631 \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
    45695: "\u0639\u0644\u064a \u0627\u0644\u0637\u0627\u0647\u0631 Aali Et-Taher \u0634\u0648\u0643\u064a\u0646 Choukine \u0643\u0641\u0631 \u062a\u0628\u0646\u064a\u062a Kfar Tibnit \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
    45696: "\u0627\u0644\u0642\u0631\u0639\u0648\u0646 Qaraaoun \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
    45698: "\u0637\u064a\u0628\u0629 \u0645\u0631\u062c\u0639\u064a\u0648\u0646 Taybet Matjaayoun \u0643\u0641\u0631\u0643\u064a\u0644\u0627 Kfar Kila \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
    45726: "\u062f\u064a\u0631 \u0646\u0637\u0627\u0631 Deir Ntar \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
    45730: "\u0628\u0627\u0641\u0644\u064a\u0647 Bafliye \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
    45731: "\u062a\u0648\u0644\u064a\u0646 Touline \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
    45733: "\u0642\u0639\u0642\u0639\u064a\u0629 \u0627\u0644\u062c\u0633\u0631 Qaaqaaiyet Ej-Jisr \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
    45734: "\u0632\u0648\u0637\u0631 \u0627\u0644\u063a\u0631\u0628\u064a\u0629 Zaoutar El-Gharbiye \u0632\u0648\u0637\u0631 \u0627\u0644\u0634\u0631\u0642\u064a\u0629 Zaoutar Ech-Charqiye \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
    45740: "\u062d\u0631\u0648\u0641 Harouf En-Nabatiyeh \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
    45741: "\u0645\u064a\u0641\u062f\u0648\u0646 Mayfadoun \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
    45765: "\u062a\u0648\u0644\u064a\u0646 Touline \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
    45772: "\u0627\u0644\u0645\u0646\u0635\u0648\u0631\u064a Mansouri Sour \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
    45775: "\u0635\u064a\u0631 \u0627\u0644\u063a\u0631\u0628\u064a\u0629 Sir El-Gharbiye \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
    45800: "\u0645\u062c\u062f\u0644 \u0633\u0644\u0645 Majdel Selm \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
    45801: "\u0635\u0631\u064a\u0641\u0627 Srifa \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
    45802: "\u0634\u0647\u0627\u0628\u064a\u0629 Chehabiye \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
    45804: "\u0644\u0628\u0627\u064a\u0627 Libbaya BG \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
    45806: "\u0634\u0648\u0643\u064a\u0646 Choukine \u0645\u064a\u0641\u062f\u0648\u0646 Mayfadoun \u0632\u0648\u0637\u0631 \u0627\u0644\u063a\u0631\u0628\u064a\u0629 Zaoutar El-Gharbiye \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
    45811: "\u0642\u0628\u0631\u064a\u062e\u0627 Qabrikha \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
    45812: "\u064a\u062d\u0645\u0631 \u0628\u0642\u0627\u0639 \u0627\u0644\u063a\u0631\u0628\u064a Yohmor BG \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
    45814: "\u062d\u0631\u0648\u0641 Harouf En-Nabatiyeh \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
    45817: "\u0643\u0641\u0631 \u0631\u0645\u0627\u0646 Kfar Roummane \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
    45819: "\u062f\u064a\u0631 \u0642\u0627\u0646\u0648\u0646 \u0627\u0644\u0646\u0647\u0631 Deir Qanoun En-Nahr \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
    45821: "\u0635\u0648\u0627\u0646\u0629 Souanet Jbayl \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
    45823: "\u0645\u064a\u0641\u062f\u0648\u0646 Mayfadoun \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
    45829: "\u0641\u0631\u0648\u0646 Froun \u0639\u0644\u0645\u0627\u0646\u0629 Aalmane Marjaayoun \u0645\u0633\u064a\u0631\u0629 \u062d\u064a\u0637\u0629 \u0648\u062d\u0630\u0631",
}

IGNORED_RED_ALERT_MESSAGE_IDS: set[int] = {
    45732,
}


def _air_keyword_phrases(meaning: str) -> tuple[str, ...]:
    return tuple(
        entry.term
        for entry in load_terminology("terminology/condition_labels.yaml")
        if entry.category == "air_violation_keyword" and entry.meaning == meaning
    )


# IDs stay code-only (Phase 2.5). Standard Arabic phrases load from terminology;
# OCR/English typos remain local to Red Alert ingestion.
AIR_KEYWORDS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (
        36,
        _air_keyword_phrases("Drone / recon")
        + (
            # Common Tesseract output from Red Alert drone-map headers.
            "معم سر",
            "معمر سر",
        ),
    ),
    (35, _air_keyword_phrases("Warplane")),
    (
        38,
        _air_keyword_phrases("Helicopter")
        + (
            # Common Tesseract substitution in Red Alert helicopter headers.
            "كوترية",
        ),
    ),
)
_NON_LOCATION_TERMS = frozenset(
    {
        "لبنان",
        "تحليق",
        "تحديث",
        "مسير",
        "مسيره",
        "مقاتلات حربيه",
        "طيران حربي",
        "اقصى درجات الحذر",
        "الخريطه المباشره",
    }
)
HASHTAG_RE = re.compile(r"#([^\s#]+)")
STYLE_URL_RE = re.compile(r"url\(['\"]?([^'\")]+)")
PREVIEW_BOILERPLATE_PARTS = (
    "الخريطة",
    "تبرع الان",
    "عزز القناة",
    "am",
    "o",
)
NON_EVENT_NOTICE_PARTS = (
    "احصاءات نهاية اليوم",
    "إحصاءات نهاية اليوم",
    "اجمالي التنبيهات",
    "إجمالي التنبيهات",
    "اكثر القرى رصدا",
    "أكثر القرى رصداً",
    "نرجو منكم ابلاغنا فورا",
    "عبر البوت الجديد",
    "tawasulra bot",
    "redalertlb twasol bot",
)
NON_AIR_DRONE_WORD_PATTERNS = (
    "جزء من هذه المسيرة",
    "من هذه المسيرة",
    "هذه المسيرة",
    "بدأنا بمجموعه",
    "بدأنا بمجموعة",
    "منذ 20 تشرين الثاني 2025",
)
BARE_DRONE_KEYWORDS = (
    "طيران مسير",
    "طيران مسيّر",
    "طائرة مسيرة",
    "مسيرة",
    "مسيّرة",
    "مسيّر",
    "مسيرات",
    "مسيره",
    "مسير",
    "درون",
    "drone",
    "uav",
    # Lebanese news shorthand for a drone/UAV (for example,
    # "محلقة إسرائيلية تحلق..."). It is not a helicopter term.
    "محلقة",
)
# Drone words that never mean anything else, matched on whole tokens so the
# feminine "مسيرة" (which also means a march/procession) keeps needing context.
# "مسيّر" folds to "مسير" under Arabic normalization.
UNAMBIGUOUS_DRONE_TOKENS = ("درون", "drone", "uav", "مسير", "محلقة")
DRONE_CONTEXT_KEYWORDS = (
    "redalert.com.lb",
    RED_ZONE_OCR_MARKER,
    "طيران",
    "طائرة",
    "الطيران المسير",
    "المسير المعادي",
    "حيطة",
    "حذر",
    "فوق",
    "تحليق",
)
HELICOPTER_KEYWORDS = (
    "طيران مروحي",
    "مروحية",
    "مروحيات",
    "هليكوبتر",
    "helicopter",
    # OCR substitution in Red Alert helicopter map headers.
    "كوترية",
)
HELICOPTER_FLIGHT_KEYWORDS = (
    "تحلق",
    "يحلق",
    "تحليق",
    "تحوم",
    "تحويم",
    "حلقت",
    "hover",
    "hovering",
    "flying",
    "flies",
)

SUPPORTED_DELIVERY_METHODS = frozenset({"public_preview", "telegram_api"})
HOURS_FETCH_LIMIT_PER_HOUR = 60
HOURS_FETCH_LIMIT_CAP = 1000


def fetch_limit_for_hours(hours: int, base_limit: int) -> int:
    requested = max(base_limit, hours * HOURS_FETCH_LIMIT_PER_HOUR)
    return min(requested, HOURS_FETCH_LIMIT_CAP)


def posts_within_window(
    posts: list[RedAlertPost],
    min_message_datetime: datetime | None,
) -> list[RedAlertPost]:
    if min_message_datetime is None:
        return list(posts)
    return [
        post
        for post in posts
        if not IngestSourceAction._is_before_cutoff(
            post.message_datetime,
            min_message_datetime,
        )
    ]


def normalize_arabic(value: str) -> str:
    value = value.replace("_", " ").strip().casefold()
    value = re.sub(r"[\u064b-\u065f\u0670\u0640]", "", value)
    value = value.translate(str.maketrans("أإآٱىةؤئ", "اااايهوي"))
    value = re.sub(r"[^\w\s\-]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


@dataclass(frozen=True)
class RedAlertPost:
    message_id: int
    message_datetime: datetime
    text: str
    link: str
    image_urls: tuple[str, ...] = ()
    image_blobs: tuple[bytes, ...] = ()
    collector: str = "telegram_public_preview"

    def raw_payload(self, channel_username: str) -> dict[str, object]:
        return {
            "external_message_id": f"telegram:{channel_username}:{self.message_id}",
            "message_datetime": self.message_datetime.isoformat(),
            "raw_text": self.text,
            "source_platform": "telegram",
            "source_name": SOURCE_NAME,
            "origin_account": f"@{channel_username}",
            "source_link": self.link,
            "image_urls": list(self.image_urls),
            "collector": self.collector,
        }


def parse_public_preview(html: str, channel_username: str) -> list[RedAlertPost]:
    page = BeautifulSoup(html, "html.parser")
    posts: list[RedAlertPost] = []
    for node in page.select(".tgme_widget_message"):
        post_reference = node.get("data-post")
        time_node = node.select_one("time")
        if not post_reference or time_node is None:
            continue
        raw_datetime = time_node.get("datetime")
        if not raw_datetime:
            continue
        try:
            message_id = int(post_reference.rsplit("/", 1)[-1])
            message_datetime = datetime.fromisoformat(raw_datetime.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        text_node = node.select_one(".tgme_widget_message_text")
        text = text_node.get_text("\n", strip=True) if text_node else ""
        image_urls: list[str] = []
        for image_node in node.select(".tgme_widget_message_photo_wrap"):
            match = STYLE_URL_RE.search(image_node.get("style") or "")
            if match:
                image_urls.append(match.group(1))
        posts.append(
            RedAlertPost(
                message_id=message_id,
                message_datetime=message_datetime,
                text=text,
                link=f"https://t.me/{channel_username}/{message_id}",
                image_urls=tuple(image_urls),
            )
        )
    # Process newest posts first so a fresh alert is not delayed behind OCR for
    # older image posts still visible in Telegram's public preview window.
    return sorted(posts, key=lambda post: post.message_id, reverse=True)


def classify_condition(text: str) -> int | None:
    normalized = normalize_arabic(text)
    if any(normalize_arabic(part) in normalized for part in NON_EVENT_NOTICE_PARTS):
        return None
    if any(normalize_arabic(part) in normalized for part in NON_AIR_DRONE_WORD_PATTERNS):
        return None
    # Drone identity wins before every helicopter rule. Arabic normalization
    # folds spelling/tashkeel variants, while English tokens use word bounds.
    if any(normalize_arabic(term) in normalized for term in BARE_DRONE_KEYWORDS):
        if any(
            normalize_arabic(context) in normalized
            for context in DRONE_CONTEXT_KEYWORDS
        ) or any(term in normalized.split() for term in UNAMBIGUOUS_DRONE_TOKENS):
            return 36
    has_helicopter = any(
        normalize_arabic(term) in normalized for term in HELICOPTER_KEYWORDS
    )
    has_flight = any(
        normalize_arabic(term) in normalized for term in HELICOPTER_FLIGHT_KEYWORDS
    )
    if has_helicopter:
        return 38 if has_flight else None
    for condition_id, keywords in AIR_KEYWORDS:
        # Helicopter (38) is already decided above: it needs hover language.
        # Recon phrases must still reach 36 here; the guard below keeps the
        # bare drone words context-gated.
        if condition_id == 38:
            continue
        for keyword in keywords:
            normalized_keyword = normalize_arabic(keyword)
            if normalized_keyword not in normalized:
                continue
            if (
                condition_id == 36
                and normalized_keyword in {normalize_arabic(part) for part in BARE_DRONE_KEYWORDS}
                and not any(normalize_arabic(context) in normalized for context in DRONE_CONTEXT_KEYWORDS)
            ):
                continue
            return condition_id
    if (
        "redalert com lb" in normalized
        and (
            normalize_arabic("حيطة") in normalized
            or normalize_arabic("خبطة") in normalized
        )
        and normalize_arabic("حذر") in normalized
    ):
        # Red Alert's map card is a drone/surveillance alert. Explicit
        # warplane/helicopter keywords have already been checked above.
        return 36
    return None


def is_preview_boilerplate(text: str) -> bool:
    remaining = normalize_arabic(text)
    for part in PREVIEW_BOILERPLATE_PARTS:
        remaining = remaining.replace(normalize_arabic(part), " ")
    # Telegram preview widgets append short changing markers such as <JM> or
    # <MS>. They are not message content and must not prevent image OCR.
    remaining = re.sub(r"(?<!\w)[a-z]{1,3}(?!\w)", " ", remaining)
    return not re.sub(r"[\W_]+", "", remaining, flags=re.UNICODE)


def _alias_matches_in(candidate_text: str, villages: list[Village]) -> list[tuple[Village, str]]:
    normalized_candidate = normalize_arabic(candidate_text)
    latin_candidate_words = latin_location_words(candidate_text)
    matches: dict[int, tuple[Village, str]] = {}
    for alias, acs_code in RED_ALERT_VILLAGE_ALIASES.items():
        normalized_alias = normalize_arabic(alias)
        if re.search(r"[\u0600-\u06ff]", alias):
            alias_found = normalized_alias in normalized_candidate
        else:
            alias_found = latin_name_in_words(latin_location_words(alias), latin_candidate_words)
        if alias_found:
            village = next(
                (item for item in villages if getattr(item, "acs_code", None) == acs_code),
                None,
            )
            if village is not None:
                current = matches.get(village.id)
                if current is None or len(alias) > len(current[1]):
                    matches[village.id] = (village, alias)
    return list(matches.values())


def match_villages(text: str, villages: list[Village]) -> list[tuple[Village, str]]:
    location_text = text.rsplit(RED_ZONE_OCR_MARKER, 1)[-1] if RED_ZONE_OCR_MARKER in text else text
    return _alias_matches_in(location_text, villages)


def match_village(text: str, villages: list[Village]) -> tuple[Village, str] | None:
    """Match only canonical village names loaded from Data/Villages.json.

    Caza labels and approximate spellings must not be converted into a village:
    doing that previously selected an arbitrary/nearest village from the same
    caza even when that village was not named by the alert.
    """
    # When focused red-zone OCR is available, ignore labels elsewhere on the
    # map. Those labels are nearby places, not affected villages.
    location_text = text.rsplit(RED_ZONE_OCR_MARKER, 1)[-1] if RED_ZONE_OCR_MARKER in text else text
    normalized_text = normalize_arabic(location_text)
    normalized_latin_text = normalize_latin_location_token(location_text)
    alias_matches = _alias_matches_in(location_text, villages)
    if alias_matches:
        if RED_ZONE_OCR_MARKER in text and len({village.id for village, _alias in alias_matches}) > 1:
            return None
        return max(alias_matches, key=lambda item: len(item[1]))
    if RED_ZONE_OCR_MARKER in text:
        return None
    hashtags = [normalize_arabic(value) for value in HASHTAG_RE.findall(location_text)]
    non_location_terms = {normalize_arabic(value) for value in _NON_LOCATION_TERMS}
    candidates = [value for value in hashtags if value and value not in non_location_terms]
    indexed: list[tuple[str, Village]] = []
    for village in villages:
        for name in (
            getattr(village, "ref_name_ar", None),
            getattr(village, "acs_name", None),
            getattr(village, "cad_name", None),
        ):
            normalized_name = normalize_arabic(name or "")
            if normalized_name:
                indexed.append((normalized_name, village))
    for candidate in candidates:
        for name, village in indexed:
            if candidate == name:
                return village, candidate
    matches = [
        (len(name), name, village)
        for name, village in indexed
        if len(name) >= 3 and re.search(rf"(?<!\w){re.escape(name)}(?!\w)", normalized_text)
    ]
    if RED_ZONE_OCR_MARKER in text and len({village.id for _length, _name, village in matches}) > 1:
        return None
    if not matches:
        latin_text = normalize_latin_location_token(location_text)
        latin_matches: list[tuple[int, str, Village]] = []
        for village in villages:
            for canonical_name in (
                getattr(village, "ref_name_en", None),
                getattr(village, "acs_name", None),
                getattr(village, "cad_name", None),
            ):
                normalized_name = normalize_latin_location_token(canonical_name or "")
                if len(normalized_name) >= 4 and normalized_name in latin_text:
                    latin_matches.append((len(normalized_name), canonical_name or "", village))
        if not latin_matches:
            return None
        if RED_ZONE_OCR_MARKER in text and len({village.id for _length, _name, village in latin_matches}) > 1:
            return None
        _length, canonical_name, village = max(latin_matches, key=lambda item: item[0])
        return village, canonical_name
    _length, name, village = max(matches, key=lambda item: item[0])
    return village, name


class RedAlertCollector:
    def __init__(
        self,
        db: Session,
        *,
        delivery_method: str = "public_preview",
        channel_username: str = "redlinkleb",
        fetch_limit: int = 20,
        request_timeout: int = 30,
        ocr_enabled: bool = True,
        http_get: Callable[..., httpx.Response] = httpx.get,
        air_violation_service: RedAlertAirViolationService | None = None,
        min_message_datetime: datetime | None = None,
    ) -> None:
        self.db = db
        self.delivery_method = self._normalize_delivery_method(delivery_method)
        self.channel_username = channel_username.removeprefix("@")
        self.fetch_limit = max(1, fetch_limit)
        self.request_timeout = request_timeout
        self.ocr_enabled = ocr_enabled
        self.http_get = http_get
        self.min_message_datetime = min_message_datetime
        self.air_violation_service = air_violation_service or RedAlertAirViolationService(
            AirViolationRepository(db), classify_condition, match_village, match_villages
        )

    def collect_once(self) -> dict[str, int]:
        source = self._ensure_source()
        self._ensure_unclassified_air_condition()
        started_at = datetime.now(timezone.utc)
        fetched_posts = self._fetch_posts()
        posts = posts_within_window(fetched_posts, self.min_message_datetime)
        skipped_before_cutoff = len(fetched_posts) - len(posts)
        villages = list(self.db.scalars(select(Village).where(Village.is_active.is_(True))))
        saved = duplicates = failed = air_violations = new_air_violations = 0
        for post in posts:
            if post.message_id in IGNORED_RED_ALERT_MESSAGE_IDS:
                continue
            external_id = f"telegram:{self.channel_username}:{post.message_id}"
            existing = self.db.scalar(
                select(RawMessage).where(
                    RawMessage.source_id == source.id,
                    RawMessage.external_message_id == external_id,
                )
            )
            if existing is not None:
                duplicates += 1
                try:
                    routed = self._enrich_existing_with_ocr(existing, post, villages)
                    # Re-evaluate OCR messages rejected by an older classifier
                    # when a newly supported OCR spelling now identifies them.
                    if (
                        not routed
                        and existing.status == MessageStatus.rejected
                        and (existing.raw_payload or {}).get("ocr_text")
                        and classify_condition(existing.raw_text or "") is not None
                    ):
                        routed = self.air_violation_service.process(existing, villages)
                    if (
                        not routed
                        and existing.status == MessageStatus.routed_air_violation
                        and (existing.raw_payload or {}).get("ocr_text")
                        and classify_condition(existing.raw_text or "") is not None
                    ):
                        routed = self.air_violation_service.process(existing, villages)
                    if routed:
                        air_violations += 1
                    self.db.commit()
                except Exception:
                    self.db.rollback()
                    failed += 1
                    logger.exception("Red Alert OCR enrichment failed message_id=%s", post.message_id)
                continue
            text = self._text_with_optional_ocr(post)
            # The Red Alert feed also contains donations, advertisements,
            # artillery reports, and other operational notices. Inspect them
            # in memory, but persist only recognized air-violation news.
            if classify_condition(text) is None:
                continue
            payload = post.raw_payload(self.channel_username)
            if text != post.text:
                payload["preview_text"] = post.text
                payload["ocr_text"] = text
                payload["ocr_version"] = OCR_VERSION
                payload["raw_text"] = text
            message = RawMessage(
                source_id=source.id,
                external_message_id=external_id,
                source_platform="telegram",
                source_name=SOURCE_NAME,
                origin_platform="telegram",
                origin_account=f"@{self.channel_username}",
                raw_text=text,
                raw_payload=payload,
                message_datetime=post.message_datetime,
                status=MessageStatus.pending,
            )
            try:
                self.db.add(message)
                self.db.flush()
                saved += 1
                if self.air_violation_service.process(message, villages):
                    air_violations += 1
                    new_air_violations += 1
                self.db.commit()
            except IntegrityError:
                self.db.rollback()
                duplicates += 1
            except Exception:
                self.db.rollback()
                failed += 1
                logger.exception("Red Alert post ingestion failed message_id=%s", post.message_id)
        # Polling the public preview is frequent and usually returns the same
        # posts. Record an ingestion run only when a new air-violation row was
        # actually created; duplicate-only and unrelated polls are operational
        # noise and would otherwise produce thousands of empty log entries.
        if new_air_violations > 0:
            self._write_log(source.id, new_air_violations, started_at)
        return {
            "fetched": len(fetched_posts),
            "saved": saved,
            "duplicates": duplicates,
            "failed": failed,
            "air_violations": air_violations,
            "skipped_before_cutoff": skipped_before_cutoff,
        }

    def _text_with_optional_ocr(self, post: RedAlertPost) -> str:
        has_images = bool(post.image_urls or post.image_blobs)
        if not has_images or (post.text.strip() and not is_preview_boilerplate(post.text)):
            return self._text_with_broken_map_fallback(post, post.text)
        return self._text_with_broken_map_fallback(post, self._ocr_images(post) or post.text)

    def _text_with_broken_map_fallback(self, post: RedAlertPost, text: str) -> str:
        local_time = post.message_datetime.astimezone(BEIRUT_TIMEZONE)
        fallback = (
            BROKEN_RED_ALERT_MESSAGE_FALLBACKS.get(post.message_id)
            or BROKEN_RED_ALERT_MAP_FALLBACKS.get((local_time.hour, local_time.minute))
        )
        if not fallback:
            return text
        if fallback.casefold() in text.casefold():
            return text
        separator = RED_ZONE_OCR_MARKER if RED_ZONE_OCR_MARKER in text else ""
        return f"{text}\n{separator}\n{fallback}".strip()

    def _enrich_existing_with_ocr(
        self,
        message: RawMessage,
        post: RedAlertPost,
        villages: list[Village],
    ) -> bool:
        payload = dict(message.raw_payload or {})
        fallback_text = self._text_with_broken_map_fallback(post, message.raw_text or "")
        if fallback_text != (message.raw_text or ""):
            payload["preview_text"] = payload.get("preview_text") or post.text
            payload["ocr_text"] = fallback_text
            payload["ocr_version"] = OCR_VERSION
            payload["raw_text"] = fallback_text
            message.raw_payload = payload
            message.raw_text = fallback_text
            message.status = MessageStatus.pending
            message.error_message = None
            return self.air_violation_service.process(message, villages)
        if (
            int(payload.get("ocr_version") or 0) >= OCR_VERSION
            or (not post.image_urls and not post.image_blobs)
            or not is_preview_boilerplate(post.text)
        ):
            return False
        text = self._text_with_broken_map_fallback(post, self._ocr_images(post))
        if not text:
            return False
        payload["preview_text"] = post.text
        payload["ocr_text"] = text
        payload["ocr_version"] = OCR_VERSION
        payload["raw_text"] = text
        message.raw_payload = payload
        message.raw_text = text
        message.status = MessageStatus.pending
        message.error_message = None
        return self.air_violation_service.process(message, villages)

    def _fetch_posts(self) -> list[RedAlertPost]:
        if self.delivery_method == "telegram_api":
            return self._fetch_posts_from_telegram_api()
        return self._fetch_posts_from_public_preview()

    def _fetch_posts_from_public_preview(self) -> list[RedAlertPost]:
        posts_by_id: dict[int, RedAlertPost] = {}
        before: int | None = None
        while len(posts_by_id) < self.fetch_limit:
            url = f"https://t.me/s/{self.channel_username}"
            if before is not None:
                url = f"{url}?before={before}"
            response = self.http_get(
                url,
                follow_redirects=True,
                timeout=self.request_timeout,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            response.raise_for_status()
            page_posts = parse_public_preview(response.text, self.channel_username)
            if not page_posts:
                break
            new_posts = 0
            for post in page_posts:
                if post.message_id not in posts_by_id:
                    posts_by_id[post.message_id] = post
                    new_posts += 1
            oldest = min(page_posts, key=lambda post: post.message_id)
            if self.min_message_datetime and all(
                post.message_datetime < self.min_message_datetime for post in page_posts
            ):
                break
            if new_posts == 0 or oldest.message_id <= 1:
                break
            before = oldest.message_id
        return sorted(posts_by_id.values(), key=lambda post: post.message_id, reverse=True)[
            : self.fetch_limit
        ]

    def _fetch_posts_from_telegram_api(self) -> list[RedAlertPost]:
        return asyncio.run(self._fetch_posts_from_telegram_api_async())

    async def _fetch_posts_from_telegram_api_async(self) -> list[RedAlertPost]:
        try:
            from telethon import TelegramClient
            from telethon.sessions import StringSession
        except ImportError as exc:
            raise RuntimeError(
                "telethon is required when RED_ALERT_DELIVERY_METHOD=telegram_api"
            ) from exc

        from app.core.config import settings

        if not settings.telegram_api_id or not settings.telegram_api_hash:
            raise RuntimeError(
                "TELEGRAM_API_ID and TELEGRAM_API_HASH are required for telegram_api mode"
            )
        if not settings.telegram_session_string:
            raise RuntimeError(
                "TELEGRAM_SESSION_STRING is required for telegram_api mode in Docker"
            )

        client = TelegramClient(
            StringSession(settings.telegram_session_string),
            int(settings.telegram_api_id),
            settings.telegram_api_hash,
            auto_reconnect=True,
        )

        async with client:
            entity = await client.get_entity(self.channel_username)
            posts: list[RedAlertPost] = []
            async for message in client.iter_messages(entity, limit=self.fetch_limit):
                if message is None or message.id is None or message.date is None:
                    continue
                text = (message.message or "").strip()
                image_blobs: list[bytes] = []
                document = getattr(message, "document", None)
                mime_type = getattr(document, "mime_type", None)
                if message.photo or (isinstance(mime_type, str) and mime_type.startswith("image/")):
                    blob = await client.download_media(message, file=bytes)
                    if isinstance(blob, bytes) and blob:
                        image_blobs.append(blob)
                posts.append(
                    RedAlertPost(
                        message_id=message.id,
                        message_datetime=message.date.astimezone(timezone.utc),
                        text=text,
                        link=f"https://t.me/{self.channel_username}/{message.id}",
                        image_blobs=tuple(image_blobs),
                        collector="telegram_api",
                    )
                )
        return sorted(posts, key=lambda post: post.message_id, reverse=True)

    def _ocr_images(self, post: RedAlertPost) -> str:
        if not self.ocr_enabled or (not post.image_urls and not post.image_blobs):
            return ""
        try:
            import pytesseract
        except ImportError:
            logger.warning("OCR dependencies unavailable; skipping image-only Red Alert post")
            return ""
        output: list[str] = []
        for url in post.image_urls:
            try:
                response = self.http_get(
                    url,
                    follow_redirects=True,
                    timeout=self.request_timeout,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                response.raise_for_status()
                image = Image.open(io.BytesIO(response.content))
                text = pytesseract.image_to_string(image, lang="ara+eng")

                # Red Alert map cards put the alert type (for example
                # "مسيّرة") in white text in the dark top-right header. A
                # whole-image OCR pass frequently sees the map locations but
                # misses that header, causing genuine alerts to be rejected.
                header = image.crop(
                    (
                        int(image.width * 0.55),
                        0,
                        image.width,
                        int(image.height * 0.16),
                    )
                )
                header = ImageOps.autocontrast(ImageOps.grayscale(header))
                header = header.resize((header.width * 5, header.height * 5))
                header_text = pytesseract.image_to_string(
                    header,
                    lang="ara+eng",
                    config="--psm 6",
                )

                # Read only inside the red alert circle. Whole-image OCR often
                # captures nearby map labels instead of the affected village.
                rgb_image = image.convert("RGB")
                pixels = rgb_image.load()
                red_points = [
                    (x, y)
                    for y in range(int(image.height * 0.14), int(image.height * 0.90))
                    for x in range(image.width)
                    if pixels[x, y][0] > 150
                    and pixels[x, y][0] > pixels[x, y][1] * 1.35
                    and pixels[x, y][0] > pixels[x, y][2] * 1.25
                ]
                red_zone_text = ""
                if red_points:
                    xs = [point[0] for point in red_points]
                    ys = [point[1] for point in red_points]
                    margin = 10
                    if max(xs) - min(xs) > margin * 2 and max(ys) - min(ys) > margin * 2:
                        red_zone = rgb_image.crop(
                            (
                                min(xs) + margin,
                                min(ys) + margin,
                                max(xs) - margin,
                                max(ys) - margin,
                            )
                        )
                        red_zone = ImageOps.autocontrast(ImageOps.grayscale(red_zone))
                        red_zone = red_zone.resize((red_zone.width * 8, red_zone.height * 8))
                        red_zone_text = pytesseract.image_to_string(
                            red_zone,
                            lang="ara+eng",
                            config="--psm 11",
                        )

                combined_parts = [part.strip() for part in (text, header_text) if part.strip()]
                if red_zone_text.strip():
                    combined_parts.extend((RED_ZONE_OCR_MARKER, red_zone_text.strip()))
                combined = "\n".join(combined_parts)
                if combined:
                    output.append(combined)
            except Exception:
                logger.exception("OCR failed for Red Alert image url=%s", url)
        for index, blob in enumerate(post.image_blobs):
            try:
                image = Image.open(io.BytesIO(blob))
                combined = self._ocr_red_alert_image(image, pytesseract)
                if combined:
                    output.append(combined)
            except Exception:
                logger.exception(
                    "OCR failed for Red Alert telegram image message_id=%s image_index=%s",
                    post.message_id,
                    index,
                )
        return "\n".join(output)

    @staticmethod
    def _ocr_red_alert_image(image: Image.Image, pytesseract_module) -> str:
        text = pytesseract_module.image_to_string(image, lang="ara+eng")
        header = image.crop(
            (
                int(image.width * 0.55),
                0,
                image.width,
                int(image.height * 0.16),
            )
        )
        header = ImageOps.autocontrast(ImageOps.grayscale(header))
        header = header.resize((header.width * 5, header.height * 5))
        header_text = pytesseract_module.image_to_string(
            header,
            lang="ara+eng",
            config="--psm 6",
        )

        red_zone_text = RedAlertCollector._ocr_red_zone_text(image, pytesseract_module)
        combined_parts = [part.strip() for part in (text, header_text) if part.strip()]
        if red_zone_text.strip():
            combined_parts.extend((RED_ZONE_OCR_MARKER, red_zone_text.strip()))
        return "\n".join(combined_parts)

    @staticmethod
    def _ocr_red_zone_text(image: Image.Image, pytesseract_module) -> str:
        rgb_image = image.convert("RGB")
        pixels = rgb_image.load()
        red_points = [
            (x, y)
            for y in range(int(image.height * 0.14), int(image.height * 0.90))
            for x in range(image.width)
            if pixels[x, y][0] > 150
            and pixels[x, y][0] > pixels[x, y][1] * 1.35
            and pixels[x, y][0] > pixels[x, y][2] * 1.25
        ]
        if not red_points:
            return ""
        xs = [point[0] for point in red_points]
        ys = [point[1] for point in red_points]
        margin = 10
        if max(xs) - min(xs) <= margin * 2 or max(ys) - min(ys) <= margin * 2:
            return ""
        red_zone = rgb_image.crop(
            (
                min(xs) + margin,
                min(ys) + margin,
                max(xs) - margin,
                max(ys) - margin,
            )
        )
        red_zone = ImageOps.autocontrast(ImageOps.grayscale(red_zone))
        red_zone = red_zone.resize((red_zone.width * 8, red_zone.height * 8))
        return pytesseract_module.image_to_string(
            red_zone,
            lang="ara+eng",
            config="--psm 11",
        )

    def _ensure_source(self) -> Source:
        source = self.db.scalar(select(Source).where(Source.external_id == SOURCE_EXTERNAL_ID))
        if source is not None:
            if not source.is_active:
                source.is_active = True
            source.config = {
                **(source.config or {}),
                "channel_username": self.channel_username,
                "channel_url": f"https://t.me/{self.channel_username}",
                "delivery_method": self.delivery_method,
            }
            self.db.commit()
            return source
        source = Source(
            type=SourceType.telegram,
            name=SOURCE_NAME,
            external_id=SOURCE_EXTERNAL_ID,
            config={
                "channel_username": self.channel_username,
                "channel_url": f"https://t.me/{self.channel_username}",
                "delivery_method": self.delivery_method,
            },
            is_active=True,
        )
        self.db.add(source)
        self.db.commit()
        return source

    def _ensure_unclassified_air_condition(self) -> None:
        if self.db.get(Condition, UNCLASSIFIED_AIR_CONDITION_ID) is not None:
            return
        self.db.add(
            Condition(
                id=UNCLASSIFIED_AIR_CONDITION_ID,
                action_en="Air Activity - Needs Verification",
                action_ar="نشاط جوي بحاجة إلى التحقق",
                note="Fallback for Red Alert maps with unreadable aircraft type.",
                is_active=True,
            )
        )
        self.db.commit()

    @staticmethod
    def _normalize_delivery_method(value: str) -> str:
        normalized = value.strip().casefold().replace("-", "_")
        if normalized not in SUPPORTED_DELIVERY_METHODS:
            supported = ", ".join(sorted(SUPPORTED_DELIVERY_METHODS))
            raise ValueError(
                f"Unsupported Red Alert delivery method {value!r}; expected one of: {supported}"
            )
        return normalized

    def _write_log(
        self,
        source_id: int,
        routed: int,
        started_at: datetime,
    ) -> None:
        from app.logs.models import IngestionLog

        self.db.add(
            IngestionLog(
                source_id=source_id,
                messages_fetched=routed,
                messages_parsed=routed,
                messages_failed=0,
                source_platforms=["telegram"],
                platform_breakdown={
                    "telegram": {
                        "fetched": routed,
                        "parsed": routed,
                        "flagged": 0,
                        "failed": 0,
                        "blocked": 0,
                    }
                },
                status="completed",
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
            )
        )
        self.db.commit()
