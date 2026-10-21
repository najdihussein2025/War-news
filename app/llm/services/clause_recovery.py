"""Conservative deterministic recovery for inline action clauses.

TODO: action recognition intentionally duplicates the minimum sectioned-list
vocabulary; that module is owned by a separate in-flight change.
"""
from __future__ import annotations

import re

from app.llm.dtos import ExtractionCasualties, ExtractionSubEvent, VillageRoleEntry
from app.news.services.matching.condition_evidence_override import condition_fallback_from_text
from app.news.services.matching.village_mentions import find_village_mentions

_SEPARATOR = re.compile(r"\s+-\s+|\s+(?:تزامنا\s+مع|بالتزامن\s+مع|ترافق\s+مع|مترافقا\s+مع)\s+|\s+و(?=(?:قصف|استهداف|تمشيط|دبابة|اطلاق))")
_ACTION = re.compile(r"قصف|قذائف|قنابل|تمشيط|دبابة|ميركافا|استهدف|اطلاق", re.UNICODE)
_BOILERPLATE = re.compile(r"^\s*(?:#\S+\s*)+(?:[\-–—]\s*)?|^\s*(?:الوطنية|النبطية)\s*[\-–—]\s*", re.UNICODE)


def recover_clause_sub_events(post_text: str) -> list[ExtractionSubEvent]:
    """Recover literal action×location clauses, without fuzzy prose matching."""
    text = _BOILERPLATE.sub("", post_text or "").strip()
    parts = [part.strip() for part in _SEPARATOR.split(text) if part.strip()]
    events: list[ExtractionSubEvent] = []
    inherited: list[VillageRoleEntry] = []
    for part in parts:
        if not _ACTION.search(part):
            continue
        mentions = find_village_mentions(part)
        locations = [VillageRoleEntry(village=item.text, evidence_span=part) for item in mentions if not item.ambiguous]
        if not locations:
            locations = inherited
        if not locations:
            continue
        action = condition_fallback_from_text(part)
        if action is None:
            continue
        events.append(ExtractionSubEvent(locations=locations, action_text=action, casualties=ExtractionCasualties(), evidence_span=part))
        if mentions:
            inherited = locations
    return events
