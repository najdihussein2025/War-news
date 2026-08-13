import re
import string

from sqlalchemy import func
from sqlalchemy.sql.elements import ColumnElement

ARABIC_DIACRITICS_RE = re.compile(r"[\u064b-\u0652\u0640]")
MULTIPLE_SPACES_RE = re.compile(r"\s+")
ARABIC_EDGE_PUNCTUATION = "،.؛!؟\"'"
ENGLISH_EDGE_PUNCTUATION = string.punctuation + "،؛؟"
ARABIC_ALEF_VARIANTS = "أإآٱة"
ARABIC_NORMALIZED_VARIANTS = "ااااه"


def normalize_arabic_text(text: str) -> str:
    normalized = ARABIC_DIACRITICS_RE.sub("", text)
    normalized = normalized.translate(
        str.maketrans(ARABIC_ALEF_VARIANTS, ARABIC_NORMALIZED_VARIANTS)
    )
    normalized = normalized.strip().strip(ARABIC_EDGE_PUNCTUATION)
    return MULTIPLE_SPACES_RE.sub(" ", normalized).strip()


def normalize_english_text(text: str) -> str:
    normalized = text.lower().strip().strip(ENGLISH_EDGE_PUNCTUATION)
    return MULTIPLE_SPACES_RE.sub(" ", normalized).strip()


def normalize_arabic_sql(column: ColumnElement[str]) -> ColumnElement[str]:
    """Build the PostgreSQL equivalent of :func:`normalize_arabic_text`."""
    without_diacritics = func.regexp_replace(
        column,
        "[\u064b-\u0652\u0640]",
        "",
        "g",
    )
    normalized_letters = func.translate(
        without_diacritics,
        ARABIC_ALEF_VARIANTS,
        ARABIC_NORMALIZED_VARIANTS,
    )
    without_edge_punctuation = func.btrim(
        func.btrim(normalized_letters),
        ARABIC_EDGE_PUNCTUATION,
    )
    return func.btrim(
        func.regexp_replace(without_edge_punctuation, r"\s+", " ", "g")
    )
