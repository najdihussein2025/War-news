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
