from __future__ import annotations

import asyncio
import io
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

import httpx
from bs4 import BeautifulSoup
from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.news.models import Condition, MessageStatus, RawMessage, Village
from app.news.repositories.air_violation_repository import AirViolationRepository
from app.news.services.red_alert_air_violation_service import RedAlertAirViolationService
from app.sources.actions.ingest_source_action import IngestSourceAction
from app.sources.models import Source, SourceType

logger = logging.getLogger(__name__)

SOURCE_EXTERNAL_ID = "red_alert_telegram"
SOURCE_NAME = "Red Alert Lebanon"
UNCLASSIFIED_AIR_CONDITION_ID = 45
OCR_VERSION = 3
RED_ZONE_OCR_MARKER = "__RED_ZONE_TEXT__"
# Exact labels used by the Red Alert map, mapped to canonical Villages.json
# ACS codes. These are spelling aliases only; they never select a nearby place.
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
}
AIR_KEYWORDS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (35, ("طيران حربي", "مقاتلات حربية", "مقاتله حربيه", "مقاتلات حربيه")),
    (
        36,
        (
            "طيران استطلاعي",
            "طائره استطلاع",
            "مسيره",
            "مسير",
            # Common Tesseract output from Red Alert drone-map headers.
            "معم سر",
            "معمر سر",
        ),
    ),
    (
        38,
        (
            "طيران مروحي",
            "مروحيه",
            "هليكوبتر",
            "apache",
            "ah-64",
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

SUPPORTED_DELIVERY_METHODS = frozenset({"public_preview", "telegram_api"})
HOURS_FETCH_LIMIT_PER_HOUR = 40
HOURS_FETCH_LIMIT_CAP = 200


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
    for condition_id, keywords in AIR_KEYWORDS:
        if any(normalize_arabic(keyword) in normalized for keyword in keywords):
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
    for alias, acs_code in RED_ALERT_VILLAGE_ALIASES.items():
        normalized_alias = normalize_arabic(alias)
        alias_found = (
            normalized_alias in normalized_text
            if re.search(r"[\u0600-\u06ff]", alias)
            else normalize_latin_location_token(alias) in normalized_latin_text
        )
        if alias_found:
            village = next((item for item in villages if item.acs_code == acs_code), None)
            if village is not None:
                return village, alias
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
            AirViolationRepository(db), classify_condition, match_village
        )

    def collect_once(self) -> dict[str, int]:
        source = self._ensure_source()
        self._ensure_unclassified_air_condition()
        started_at = datetime.now(timezone.utc)
        fetched_posts = self._fetch_posts()
        posts = posts_within_window(fetched_posts, self.min_message_datetime)
        skipped_before_cutoff = len(fetched_posts) - len(posts)
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
                    if routed:
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
        if air_violations > 0:
            self._write_log(source.id, air_violations, started_at)
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
            return post.text
        return self._ocr_images(post) or post.text

    def _enrich_existing_with_ocr(
        self,
        message: RawMessage,
        post: RedAlertPost,
        villages: list[Village],
    ) -> bool:
        payload = dict(message.raw_payload or {})
        if (
            int(payload.get("ocr_version") or 0) >= OCR_VERSION
            or (not post.image_urls and not post.image_blobs)
            or not is_preview_boilerplate(post.text)
        ):
            return False
        text = self._ocr_images(post)
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
        response = self.http_get(
            f"https://t.me/s/{self.channel_username}",
            follow_redirects=True,
            timeout=self.request_timeout,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        response.raise_for_status()
        return parse_public_preview(response.text, self.channel_username)

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
                text = pytesseract.image_to_string(image, lang="ara+eng")
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
                logger.exception(
                    "OCR failed for Red Alert telegram image message_id=%s image_index=%s",
                    post.message_id,
                    index,
                )
        return "\n".join(output)

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
