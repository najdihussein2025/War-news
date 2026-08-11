import re
import string

ARABIC_DIACRITICS_RE = re.compile(r"[\u064b-\u0652\u0640]")
MULTIPLE_SPACES_RE = re.compile(r"\s+")
ARABIC_EDGE_PUNCTUATION = "،.؛!؟\"'"
ENGLISH_EDGE_PUNCTUATION = string.punctuation + "،؛؟"


def normalize_arabic_text(text: str) -> str:
    normalized = ARABIC_DIACRITICS_RE.sub("", text)
    normalized = normalized.translate(
        str.maketrans(
            {
                "أ": "ا",
                "إ": "ا",
                "آ": "ا",
                "ٱ": "ا",
                "ة": "ه",
            }
        )
    )
    normalized = normalized.strip().strip(ARABIC_EDGE_PUNCTUATION)
    return MULTIPLE_SPACES_RE.sub(" ", normalized).strip()


def normalize_english_text(text: str) -> str:
    normalized = text.lower().strip().strip(ENGLISH_EDGE_PUNCTUATION)
    return MULTIPLE_SPACES_RE.sub(" ", normalized).strip()
