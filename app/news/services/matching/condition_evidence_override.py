from __future__ import annotations

import re

from app.core.llm_knowledge.loader import load_terminology
from app.core.text_normalization import normalize_arabic_text


_DRONE_TERMS = ("مسير", "مسيرة", "مسيّرة", "طائرة مسيرة", "طيران مسير", "طيران مسيّر")
_DRONE_STRIKE_TERMS = (
    "غارة",
    "غارات",
    "استهداف",
    "استهدفت",
    "استهدف",
    "صاروخ",
    "ضربة",
    "قصف",
    "أطلقت",
    "اطلقت",
)
_DRONE_EXPLOSIVE_TERMS = ("مفخخة", "مفخخه", "انتحارية", "انتحاريه")
_DRONE_CRASH_TERMS = ("سقوط", "سقط", "تحطم", "تحطمت", "إسقاط", "اسقاط")
_DRONE_PRESENCE_TERMS = (
    "تحليق",
    "تحلق",
    "يحلق",
    "في الأجواء",
    "في الاجواء",
    "فوق",
)


def _is_drone_strike(normalized: str) -> bool:
    return any(term in normalized for term in _DRONE_TERMS) and any(
        term in normalized for term in _DRONE_STRIKE_TERMS
    )


def _has_drone_term(normalized: str) -> bool:
    return any(term in normalized for term in _DRONE_TERMS)


_TANK_FIRE_PATTERNS = (
    re.compile(r"قصف.{0,40}(?:دباب[ةه]|ميركافا)"),
    re.compile(r"(?:دباب[ةه]|ميركافا).{0,100}(?:تستهدف|تقصف|تطلق)"),
    # «استهدافه بشكل مباشر بدبابة إسرائيلية»: the tank is the instrument.
    re.compile(r"استهداف\w{0,3}.{0,40}ب(?:دباب[ةه]|ميركافا)"),
)
_WARNING_RAID = re.compile(r"غار[ةه].{0,15}تحذيري|تحذيري.{0,15}غار[ةه]")
_FEIGNED_RAID = re.compile(r"غارات?.{0,15}وهمي|وهمي.{0,15}غارات?")
_AIRSTRIKE = re.compile(r"(?:غار[ةه]|غارات|أغار|اغار)")
_SMOKE_BOMB = re.compile(r"قنابل?.{0,15}دخاني")
_SOUND_BOMB = re.compile(r"(?:قنابل|قنبل[هة]).{0,15}صوتي")
_TEAR_GAS_BOMB = re.compile(r"قنابل?.{0,25}(?:مسيل|مسيله|مسيلة).{0,25}دموع")
_FLARE_BOMB = re.compile(
    r"(?:قنابل?|قذائف?|بالونات).{0,25}(?:مضيئ|انار|إنار|ضوئ|حراري)"
    r"|(?:flare|flares|illumination)",
    re.IGNORECASE,
)
_PHOSPHORUS_TERMS = tuple(
    normalize_arabic_text(entry.term)
    for entry in load_terminology("terminology/condition_labels.yaml")
    if entry.meaning == "Phosphorus Bombs"
)
_STRIKE_LANGUAGE = re.compile(
    r"غار[ةه]|غارات|قصف|استهداف|استهدف|استهدفت|انفجار|شهيد|جريح|دمار|حريق"
)
_SWEEP = re.compile(r"تمشيط|مشط")
_AERIAL_SWEEP = re.compile(
    r"(?:اباتشي|أباتشي|مروحي|هليكوبتر).{0,40}(?:تمشيط|مشط)"
    r"|(?:تمشيط|مشط).{0,40}(?:اباتشي|أباتشي|مروحي|هليكوبتر)"
)
_MINING_AND_DETONATION = re.compile(
    r"(?:تلغيم|تفجير|فجّر|فجر|يفجر|فجرت|لغم|الغام|ألغام|عبوة ناسفة)"
)


def condition_from_explicit_evidence(text: str) -> str | None:
    """Return a condition only when the weapon/action is explicit in source text."""
    normalized = " ".join(normalize_arabic_text(text or "").split())
    if _has_drone_term(normalized):
        if any(term in normalized for term in _DRONE_EXPLOSIVE_TERMS):
            return "Suicide Drone"
        if any(term in normalized for term in _DRONE_CRASH_TERMS):
            return "Drone Failure"
        if _is_drone_strike(normalized):
            return "Bombs"
        if any(term in normalized for term in _DRONE_PRESENCE_TERMS):
            return "Surveillance Aircraft"
    # A deliberate detonation, mine, or explosive device is distinct from an
    # aerial strike. This source wording must win over a generic LLM "Bombs"
    # label so that detonations are consistently routed to condition 21.
    if _MINING_AND_DETONATION.search(normalized):
        return "Mining & Detonation"
    # Munition is more specific than the delivery platform in the same clause.
    if any(term in normalized for term in _PHOSPHORUS_TERMS):
        return "Phosphorus Bombs"
    if any(pattern.search(normalized) for pattern in _TANK_FIRE_PATTERNS):
        return "Tank Fire"
    if _WARNING_RAID.search(normalized):
        return "Warning Raid"
    if _FEIGNED_RAID.search(normalized):
        return "Feigned Attacks"
    if _SMOKE_BOMB.search(normalized):
        return "Smoke Grenades"
    if _SOUND_BOMB.search(normalized):
        return "Sound Bombs"
    if _TEAR_GAS_BOMB.search(normalized):
        return "Unclassified / Needs Review"
    if _FLARE_BOMB.search(normalized) and not has_strike_language(normalized):
        return "Flare Bomb"
    if _AERIAL_SWEEP.search(normalized):
        return "Aerial Sweep"
    if _SWEEP.search(normalized):
        return "Sweeping Operations"
    if _AIRSTRIKE.search(normalized):
        return "Bombs"
    return None


_DUAL_AIRSTRIKE = re.compile(r"غارت(?:ين|ان)")
_ARTILLERY = re.compile(r"قصف.{0,15}مدفعي|قذيف(?:ة|ه|ات)?.{0,15}مدفعي")
_ENGLISH_AIRSTRIKE = re.compile(r"\b(?:air\s*strikes?|air\s*raids?|raid(?:ed|s)?|bomb(?:ed|ing|s)?)\b", re.IGNORECASE)
_ENGLISH_ARTILLERY = re.compile(r"\b(?:artillery|shell(?:ed|ing|s)?)\b", re.IGNORECASE)


def condition_fallback_from_text(text: str | None) -> str | None:
    """Last-resort condition for free-text actions the matcher could not map.

    Only used right before the Unclassified fallback, so it never overrides a
    condition the matcher already resolved.
    """
    if not text:
        return None
    explicit = condition_from_explicit_evidence(text)
    if explicit and explicit != "Unclassified / Needs Review":
        return explicit
    normalized = " ".join(normalize_arabic_text(text).split())
    if _DUAL_AIRSTRIKE.search(normalized) or _ENGLISH_AIRSTRIKE.search(text):
        return "Bombs"
    if _ARTILLERY.search(normalized) or _ENGLISH_ARTILLERY.search(text):
        return "Artillery Shelling"
    return None


def explicit_condition_labels_from_text(text: str | None) -> list[str]:
    """Return distinct, ordered source actions that can each be materialized."""
    if not text:
        return []
    normalized = " ".join(normalize_arabic_text(text).split())
    matches: list[tuple[int, str]] = []
    for pattern, label in (
        (_ARTILLERY, "Artillery Shelling"),
        (_AERIAL_SWEEP, "Aerial Sweep"),
        (_SWEEP, "Sweeping Operations"),
    ):
        match = pattern.search(normalized)
        if match is not None:
            matches.append((match.start(), label))
    labels: list[str] = []
    for _position, label in sorted(matches):
        if label not in labels:
            labels.append(label)
    return labels


def apply_condition_evidence_override(text: str, action: str | None) -> str | None:
    return condition_from_explicit_evidence(text) or action


def has_flare_language(text: str) -> bool:
    normalized = " ".join(normalize_arabic_text(text or "").split())
    return bool(_FLARE_BOMB.search(normalized))


def has_strike_language(text: str) -> bool:
    normalized = " ".join(normalize_arabic_text(text or "").split())
    return bool(_STRIKE_LANGUAGE.search(normalized))
