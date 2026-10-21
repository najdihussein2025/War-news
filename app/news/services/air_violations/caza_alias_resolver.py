from __future__ import annotations

import re

from app.core.text_normalization import normalize_arabic_text

CANONICAL_CAZA_ALIASES: dict[str, str] = {
    "tyre": "Sour",
    "sour": "Sour",
    "nabatieh": "Nabatiye",
    "nabatiye": "Nabatiye",
    "marjayoun": "Marjaayoun",
    "marjaayoun": "Marjaayoun",
    "hasbaiya": "Hasbaya",
    "hasbaya": "Hasbaya",
    "bint jbeil": "Bint Jubail",
    "bint jubail": "Bint Jubail",
    "baalbeck": "Baalbek",
    "baalbek": "Baalbek",
    "jbeil": "Jubail",
    "jubail": "Jubail",
    "west bekaa": "West Bekaa",
}

SECTOR_CAZA_ALIASES: dict[str, str] = {
    "قطاع شرقي": "Marjaayoun",
    "القطاع الشرقي": "Marjaayoun",
    "قطاع غربي": "Sour",
    "القطاع الغربي": "Sour",
    "قطاع اوسط": "Bint Jubail",
    "القطاع الاوسط": "Bint Jubail",
}


def _normalize_latin(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def resolve_caza_alias(value: str | None) -> str | None:
    if not value:
        return None

    latin = _normalize_latin(value)
    if latin in CANONICAL_CAZA_ALIASES:
        return CANONICAL_CAZA_ALIASES[latin]

    arabic = normalize_arabic_text(value)
    for alias, caza in SECTOR_CAZA_ALIASES.items():
        if normalize_arabic_text(alias) in arabic:
            return caza
    return None


def canonicalize_caza(value: str | None) -> str | None:
    if not value:
        return None
    return resolve_caza_alias(value) or value.strip() or None
