from __future__ import annotations

import re


_TANK_FIRE_PATTERNS = (
    re.compile(r"قصف.{0,40}(?:دباب[ةه]|ميركافا)"),
    re.compile(r"(?:دباب[ةه]|ميركافا).{0,100}(?:تستهدف|تقصف|تطلق)"),
)
_WARNING_RAID = re.compile(r"غار[ةه].{0,15}تحذيري|تحذيري.{0,15}غار[ةه]")
_FEIGNED_RAID = re.compile(r"غارات?.{0,15}وهمي|وهمي.{0,15}غارات?")
_AIRSTRIKE = re.compile(r"(?:غار[ةه]|غارات|أغار|اغار)")


def condition_from_explicit_evidence(text: str) -> str | None:
    """Return a condition only when the weapon is explicitly doing the firing."""
    normalized = " ".join((text or "").split())
    if any(pattern.search(normalized) for pattern in _TANK_FIRE_PATTERNS):
        return "Tank Fire"
    if _WARNING_RAID.search(normalized):
        return "Warning Raid"
    if _FEIGNED_RAID.search(normalized):
        return "Feigned Attacks"
    if _AIRSTRIKE.search(normalized):
        return "Bombs"
    return None


def apply_condition_evidence_override(text: str, action: str | None) -> str | None:
    return condition_from_explicit_evidence(text) or action
