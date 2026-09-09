import logging
import re

from app.news.interfaces import EmbeddingServiceInterface
from app.news.models import RawMessage

logger = logging.getLogger(__name__)

BOILERPLATE_PATTERNS = (
    (
        "daily summary header",
        re.compile(
            r"(?:🏴\s*)?ملخص\s+ال[اإ]عتداءات\s+"
            r"(?:لهذا اليوم|من منتصف الليل حتى الساعة)\s*:?\s*"
        ),
    ),
    (
        "Ali Shoeib channel attribution",
        re.compile(
            r"^\s*🌟?\s*صفحة الإعلامي الشهيد علي شعيب\s*[:：]\s*[●•]?\s*"
        ),
    ),
    (
        "breaking tag",
        re.compile(r"^\s*(?:🚨+|🔴+)\s*(?:عاجل\s*[|:،\-–—]?\s*)?"),
    ),
    (
        "Mehwar channel signature",
        re.compile(r"\s*T\.me/mehwaralmokawma\b.*$", re.IGNORECASE | re.DOTALL),
    ),
    (
        "Bint Jbeil WhatsApp footer",
        re.compile(
            r"\s*─{5,}.*📲\s*قناة بنت جبيل على واتساب.*$",
            re.DOTALL,
        ),
    ),
    # Added from real Khiyam/Marjaayoun and Nabatiyeh El-Faouka
    # cross-outlet duplicate-scoring examples.
    (
        "NNA attribution",
        re.compile(
            r"^\s*[«“\"']?\s*الوكالة الوطنية(?:\s+للإعلام)?"
            r"\s*[»”\"']?\s*[:：]\s*"
        ),
    ),
    (
        "Al Mayadeen correspondent attribution",
        re.compile(
            r"^\s*(?:لبنان\s*[:：]\s*)?مراسل(?:ة)?\s+الميادين"
            r"(?:\s+في\s+[^:：\n]{1,80})?\s*[:：]\s*"
        ),
    ),
    (
        "Lebanon24 attribution",
        re.compile(
            r"^\s*[«“\"']?\s*لبنان\s*24\s*[»”\"']?\s*[:：]\s*"
        ),
    ),
    (
        "Lebanon24 trailing noise",
        re.compile(
            r"(?:\s*(?:[#＃]\s*lebanon\s*24\b|"
            r"(?:https?://)?(?:www\.)?lebanon24\.com(?:/\S*)?))+\s*$",
            re.IGNORECASE,
        ),
    ),
)


def strip_boilerplate(text: str) -> str:
    cleaned = text
    for label, pattern in BOILERPLATE_PATTERNS:
        cleaned, count = pattern.subn(" ", cleaned)
        if count:
            logger.debug("Stripped %s from raw message text", label)
    return re.sub(r"\s+", " ", cleaned).strip()


class RawMessageEmbeddingService:
    def __init__(self, embedding_service: EmbeddingServiceInterface) -> None:
        self.embedding_service = embedding_service

    def generate(self, message: RawMessage) -> list[float]:
        return self.embedding_service.generate(
            strip_boilerplate(message.raw_text or "")
        )
