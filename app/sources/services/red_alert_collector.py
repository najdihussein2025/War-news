from __future__ import annotations

import io
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Callable

import httpx
from bs4 import BeautifulSoup
from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.news.dtos import MatchResultDTO, MatchResultStatus
from app.news.dtos.match_result_dto import VillageMatchResult
from app.news.models import MessageStatus, RawMessage, Village
from app.news.repositories.air_violation_repository import AirViolationRepository
from app.sources.models import Source, SourceType

logger = logging.getLogger(__name__)

SOURCE_EXTERNAL_ID = "red_alert_telegram"
SOURCE_NAME = "Red Alert Lebanon"
AIR_KEYWORDS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (35, ("طيران حربي", "مقاتلات حربية", "مقاتله حربيه", "مقاتلات حربيه")),
    (36, ("طيران استطلاعي", "طائره استطلاع", "مسيره", "مسير")),
    (38, ("طيران مروحي", "مروحيه", "هليكوبتر", "apache", "ah-64")),
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


def normalize_arabic(value: str) -> str:
    value = value.replace("_", " ").strip().casefold()
    value = re.sub(r"[\u064b-\u065f\u0670\u0640]", "", value)
    value = value.translate(str.maketrans("أإآٱىةؤئ", "اااايهوي"))
    value = re.sub(r"[^\w\s\-]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_latin_location_token(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-z]", "", value.casefold())
    return value.replace("ch", "sh")


@dataclass(frozen=True)
class RedAlertPost:
    message_id: int
    message_datetime: datetime
    text: str
    link: str
    image_urls: tuple[str, ...] = ()

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
            "collector": "telegram_public_preview",
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
    for condition_id, keywords in AIR_KEYWORDS:
        if any(normalize_arabic(keyword) in normalized for keyword in keywords):
            return condition_id
    return None


def is_preview_boilerplate(text: str) -> bool:
    remaining = normalize_arabic(text)
    for part in PREVIEW_BOILERPLATE_PARTS:
        remaining = remaining.replace(normalize_arabic(part), " ")
    # Telegram preview widgets append short changing markers such as <JM> or
    # <MS>. They are not message content and must not prevent image OCR.
    remaining = re.sub(r"(?<!\w)[a-z]{1,3}(?!\w)", " ", remaining)
    return not re.sub(r"[\W_]+", "", remaining, flags=re.UNICODE)


def match_village(text: str, villages: list[Village]) -> tuple[Village, str] | None:
    normalized_text = normalize_arabic(text)
    hashtags = [normalize_arabic(value) for value in HASHTAG_RE.findall(text)]
    non_location_terms = {normalize_arabic(value) for value in _NON_LOCATION_TERMS}
    candidates = [value for value in hashtags if value and value not in non_location_terms]
    indexed: list[tuple[str, Village]] = []
    for village in villages:
        # Alert maps often label only the caza (for example "Nabatieh")
        # rather than an individual village. Air Violations are grouped by
        # caza, so both village and caza names are valid locality evidence.
        for name in (
            village.ref_name_ar,
            village.acs_name,
            village.cad_name,
            village.caza_en,
            village.caza_ar,
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
    if not matches:
        latin_words = {
            normalize_latin_location_token(token)
            for token in re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ]{3,}", text)
        }
        # The Red Alert Tyre map labels Burj Al Shamali together with Hosh.
        # "Shamali" alone is ambiguous with other Lebanese village names.
        if {"shamali", "hosh"}.issubset(latin_words):
            target = normalize_arabic("برج الشمالي")
            for village in villages:
                if normalize_arabic(village.ref_name_ar or "") == target:
                    return village, "shamali hosh"

        # OCR/map labels frequently use a different Lebanese transliteration
        # than the reference data (Shamali vs Chemali). Match distinctive
        # English village-name tokens before falling back to caza names.
        latin_tokens = [
            normalize_latin_location_token(token)
            for token in re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ]{3,}", text)
        ]
        for token in latin_tokens:
            if len(token) < 5:
                continue
            for village in villages:
                reference_tokens = re.findall(
                    r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ]{3,}",
                    " ".join(part or "" for part in (village.acs_name, village.cad_name)),
                )
                if any(
                    SequenceMatcher(
                        None,
                        token,
                        normalize_latin_location_token(reference),
                    ).ratio()
                    >= 0.84
                    for reference in reference_tokens
                ):
                    return village, token

        # English Lebanese place names have several common transliterations
        # (for example Nabatieh/Nabatiye). Allow a close caza-name match after
        # exact Arabic/village matching has failed.
        latin_tokens = re.findall(r"[a-z][a-z\-]{3,}", normalized_text)
        for token in latin_tokens:
            for village in villages:
                caza_name = normalize_arabic(village.caza_en or "")
                if caza_name and SequenceMatcher(None, token, caza_name).ratio() >= 0.85:
                    return village, token
        return None
    _length, name, village = max(matches, key=lambda item: item[0])
    return village, name


class RedAlertCollector:
    def __init__(
        self,
        db: Session,
        *,
        channel_username: str = "redlinkleb",
        request_timeout: int = 30,
        ocr_enabled: bool = True,
        http_get: Callable[..., httpx.Response] = httpx.get,
    ) -> None:
        self.db = db
        self.channel_username = channel_username.removeprefix("@")
        self.request_timeout = request_timeout
        self.ocr_enabled = ocr_enabled
        self.http_get = http_get

    def collect_once(self) -> dict[str, int]:
        source = self._ensure_source()
        started_at = datetime.now(timezone.utc)
        response = self.http_get(
            f"https://t.me/s/{self.channel_username}",
            follow_redirects=True,
            timeout=self.request_timeout,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        response.raise_for_status()
        posts = parse_public_preview(response.text, self.channel_username)
        villages = list(self.db.scalars(select(Village).where(Village.is_active.is_(True))))
        saved = duplicates = failed = air_violations = 0
        for post in posts:
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
                    if self._enrich_existing_with_ocr(existing, post, villages):
                        air_violations += 1
                    self.db.commit()
                except Exception:
                    self.db.rollback()
                    failed += 1
                    logger.exception("Red Alert OCR enrichment failed message_id=%s", post.message_id)
                continue
            text = self._text_with_optional_ocr(post)
            payload = post.raw_payload(self.channel_username)
            if text != post.text:
                payload["preview_text"] = post.text
                payload["ocr_text"] = text
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
                if self._classify_and_route(message, villages):
                    air_violations += 1
                self.db.commit()
            except IntegrityError:
                self.db.rollback()
                duplicates += 1
            except Exception:
                self.db.rollback()
                failed += 1
                logger.exception("Red Alert post ingestion failed message_id=%s", post.message_id)
        self._write_log(source.id, len(posts), saved, failed, started_at)
        return {
            "fetched": len(posts),
            "saved": saved,
            "duplicates": duplicates,
            "failed": failed,
            "air_violations": air_violations,
        }

    def _text_with_optional_ocr(self, post: RedAlertPost) -> str:
        if not post.image_urls or (post.text.strip() and not is_preview_boilerplate(post.text)):
            return post.text
        return self._ocr_images(post.image_urls) or post.text

    def _enrich_existing_with_ocr(
        self,
        message: RawMessage,
        post: RedAlertPost,
        villages: list[Village],
    ) -> bool:
        payload = dict(message.raw_payload or {})
        if payload.get("ocr_text") or not post.image_urls or not is_preview_boilerplate(post.text):
            return False
        text = self._ocr_images(post.image_urls)
        if not text:
            return False
        payload["preview_text"] = post.text
        payload["ocr_text"] = text
        payload["raw_text"] = text
        message.raw_payload = payload
        message.raw_text = text
        message.status = MessageStatus.pending
        message.error_message = None
        return self._classify_and_route(message, villages)

    def _classify_and_route(self, message: RawMessage, villages: list[Village]) -> bool:
        text = message.raw_text or ""
        condition_id = classify_condition(text)
        if condition_id is None:
            message.filter_result = {
                "backend": "red_alert_rules",
                "verdict": "not_relevant",
                "reasoning": "No supported air-violation keyword",
                "confidence": 1.0,
                "raw_message_id": message.id,
            }
            message.status = MessageStatus.rejected
            return False
        village_match = match_village(text, villages)
        if village_match is None:
            message.filter_result = {
                "backend": "red_alert_rules",
                "verdict": "relevant",
                "reasoning": "Air violation detected but locality was not matched",
                "confidence": 1.0,
                "raw_message_id": message.id,
            }
            message.status = MessageStatus.rejected
            message.error_message = "red_alert: air violation locality unmatched"
            return False
        village, raw_location = village_match
        result = MatchResultDTO(
            village_matches=[
                VillageMatchResult(
                    matched_village_id=village.id,
                    village_confidence=1.0,
                    village_match_status=MatchResultStatus.matched,
                    village_review_required=False,
                    raw_village_text=raw_location,
                )
            ],
            any_village_low_confidence=False,
            matched_condition_id=condition_id,
            condition_confidence=1.0,
            condition_match_status=MatchResultStatus.matched,
            condition_review_required=False,
            raw_condition_text=text,
        )
        message.filter_result = {
            "backend": "red_alert_rules",
            "verdict": "relevant",
            "reasoning": "Supported air-violation keyword and locality matched",
            "confidence": 1.0,
            "raw_message_id": message.id,
        }
        message.match_result = result.model_dump(mode="json")
        message.status = MessageStatus.parsed
        self.db.flush()
        AirViolationRepository(self.db).route_from_match(message, result)
        message.status = MessageStatus.error
        message.error_message = "red_alert: routed to air_violations; not an incident"
        return True

    def _ocr_images(self, image_urls: tuple[str, ...]) -> str:
        if not self.ocr_enabled or not image_urls:
            return ""
        try:
            import pytesseract
        except ImportError:
            logger.warning("OCR dependencies unavailable; skipping image-only Red Alert post")
            return ""
        output: list[str] = []
        for url in image_urls:
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
                combined = "\n".join(part.strip() for part in (text, header_text) if part.strip())
                if combined:
                    output.append(combined)
            except Exception:
                logger.exception("OCR failed for Red Alert image url=%s", url)
        return "\n".join(output)

    def _ensure_source(self) -> Source:
        source = self.db.scalar(select(Source).where(Source.external_id == SOURCE_EXTERNAL_ID))
        if source is not None:
            if not source.is_active:
                source.is_active = True
                self.db.commit()
            return source
        source = Source(
            type=SourceType.telegram,
            name=SOURCE_NAME,
            external_id=SOURCE_EXTERNAL_ID,
            config={
                "channel_username": self.channel_username,
                "channel_url": f"https://t.me/{self.channel_username}",
                "delivery_method": "public_preview",
            },
            is_active=True,
        )
        self.db.add(source)
        self.db.commit()
        return source

    def _write_log(
        self,
        source_id: int,
        fetched: int,
        parsed: int,
        failed: int,
        started_at: datetime,
    ) -> None:
        from app.logs.models import IngestionLog

        self.db.add(
            IngestionLog(
                source_id=source_id,
                messages_fetched=fetched,
                messages_parsed=parsed,
                messages_failed=failed,
                source_platforms=["telegram"],
                platform_breakdown={
                    "telegram": {
                        "fetched": fetched,
                        "parsed": parsed,
                        "flagged": 0,
                        "failed": failed,
                        "blocked": 0,
                    }
                },
                status="completed" if failed == 0 else "failed",
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
            )
        )
        self.db.commit()
