"""Deterministic recovery for heading-and-location incident bulletins.

Some feeds publish a compact table as plain text: an action heading on one
line followed by one or more location lines.  A whole-message LLM can mistake
the later locations for alternatives to the first one.  This module only
handles the conservative shape where at least two known action headings are
present; ordinary prose remains entirely model-driven.
"""

from __future__ import annotations

import re

from app.core.text_normalization import normalize_arabic_text
from app.core.llm_knowledge.loader import load_terminology
from app.llm.dtos import ExtractionCasualties, ExtractionSubEvent, VillageRoleEntry


_BULLET_PREFIX_RE = re.compile(r"^[\s•●◦▪▫\-*–—]+")
_BETWEEN_RE = re.compile(
    r"^بين(?:\s+بلدتي)?\s+(?P<left>.+?)\s+و(?P<right>.+?)$"
)
_URL_OR_FOOTER_RE = re.compile(r"(?:https?://|www\.|#\S+|المصدر\s*:)", re.IGNORECASE)
_CONNECTOR_RE = re.compile(r"\s+(?:تزامناً\s+مع|بالتزامن\s+مع|ترافق\s+مع|مترافقاً\s+مع|وسط|إضافة\s+إلى)\s+")
_LOCATION_RE = re.compile(r"(?:بلدة|مدينة|قرية|منطقة|أطراف(?:\s+بلدة)?|محيط(?:\s+بلدة)?|باتجاه)\s+(?P<name>[\u0600-\u06ff][\u0600-\u06ff\s]{1,40}?)(?=\s*(?:[-–—،,.;؛]|$|تزامناً|بالتزامن|ترافق|مترافقاً|وسط|إضافة))")
_TARGET_RE = re.compile(r"(?:استهدف|يطال|طال|تجاه)\s+(?P<name>[\u0600-\u06ff][\u0600-\u06ff\s]{1,40}?)(?=\s*(?:[-–—،,.;؛]|$))")


def _condition_phrases() -> tuple[tuple[str, str], ...]:
    """Reuse matcher terminology as the conservative recovery vocabulary."""
    categories = {"condition_alias", "evidence_override", "condition_id_label"}
    entries = [entry for entry in load_terminology("terminology/condition_labels.yaml") if entry.category in categories]
    pairs = [(entry.term, entry.meaning) for entry in entries if entry.term]
    pairs.extend((entry.meaning, entry.meaning) for entry in entries if entry.meaning)
    return tuple(sorted(dict.fromkeys(pairs), key=lambda pair: len(pair[0]), reverse=True))


_CONDITION_PHRASES = _condition_phrases()


def _heading_action(line: str) -> str | None:
    normalized = normalize_arabic_text(line.strip(" :ـ-–—"))
    if not normalized:
        return None
    patterns = (
        r"(?:الغارات?|غارات?)\s+(?:الحربيه\s+)?(?:المعاديه|الاسرائيليه)?",
        r"(?:القصف\s+)?المدفعي(?:\s+(?:المعادي|الاسرائيلي))?",
        r"التفجيرات?",
        r"قنابل\s+(?:مضيئه|اناره|ضوئيه)",
        r"(?:عمليات\s+)?التمشيط(?:\s+بالاسلحه\s+الرشاشه)?",
    )
    if any(re.fullmatch(pattern, normalized) for pattern in patterns):
        return line.strip(" :ـ-–—")
    return None


def _location_entries(line: str) -> list[VillageRoleEntry]:
    cleaned = _BULLET_PREFIX_RE.sub("", line).strip(" ،,;؛:ـ-–—")
    if not cleaned or _URL_OR_FOOTER_RE.search(cleaned):
        return []
    between = _BETWEEN_RE.fullmatch(normalize_arabic_text(cleaned))
    if between is not None:
        evidence = cleaned
        return [
            VillageRoleEntry(
                village=between.group("left").strip(),
                evidence_span=evidence,
            ),
            VillageRoleEntry(
                village=between.group("right").strip(),
                evidence_span=evidence,
            ),
        ]
    parts = [part.strip() for part in re.split(r"[،,]", cleaned) if part.strip()]
    return [VillageRoleEntry(village=part, evidence_span=cleaned) for part in parts]


def recover_sectioned_sub_events(post_text: str) -> list[ExtractionSubEvent]:
    """Return action-scoped events for a conservative sectioned-list shape."""
    lines = [line.strip() for line in (post_text or "").splitlines() if line.strip()]
    headings = [index for index, line in enumerate(lines) if _heading_action(line)]
    if len(headings) < 2:
        return []

    events: list[ExtractionSubEvent] = []
    for position, heading_index in enumerate(headings):
        end = headings[position + 1] if position + 1 < len(headings) else len(lines)
        action = _heading_action(lines[heading_index])
        if action is None:
            continue
        locations: list[VillageRoleEntry] = []
        section_lines: list[str] = [lines[heading_index]]
        for line in lines[heading_index + 1 : end]:
            section_lines.append(line)
            locations.extend(_location_entries(line))
        if not locations:
            continue
        events.append(
            ExtractionSubEvent(
                locations=locations,
                action_text=action,
                casualties=ExtractionCasualties(),
                evidence_span="\n".join(section_lines),
            )
        )

    return events if len(events) >= 2 else []


def _action_text(clause: str) -> str | None:
    normalized = normalize_arabic_text(clause)
    for phrase, meaning in _CONDITION_PHRASES:
        if normalize_arabic_text(phrase) in normalized:
            return meaning if phrase in {"دبابة", "ميركافا"} else phrase
    return None


def _locations(clause: str) -> list[VillageRoleEntry]:
    names = [match.group("name").strip(" ،,.;؛:-–—") for match in _LOCATION_RE.finditer(clause)]
    if not names:
        names = [match.group("name").strip(" ،,.;؛:-–—") for match in _TARGET_RE.finditer(clause)]
    cleaned = [name.removeprefix("وطى ") for name in names]
    return [VillageRoleEntry(village=name) for name in dict.fromkeys(name for name in cleaned if name)]


def recover_connector_sub_events(post_text: str) -> list[ExtractionSubEvent]:
    """Recover two action/location clauses joined by an explicit connector."""
    text = (post_text or "").strip()
    match = _CONNECTOR_RE.search(text)
    if match is None or _URL_OR_FOOTER_RE.search(text):
        return []
    clauses = [text[:match.start()].strip(" ،,.;؛:-–—"), text[match.end():].strip(" ،,.;؛:-–—")]
    actions = [_action_text(clause) for clause in clauses]
    if not all(actions):
        return []
    locations = [_locations(clause) for clause in clauses]
    if not locations[0] and not locations[1]:
        return []
    if not locations[0]: locations[0] = locations[1]
    if not locations[1]: locations[1] = locations[0]
    return [ExtractionSubEvent(locations=clause_locations, action_text=action, casualties=ExtractionCasualties(), evidence_span=clause) for clause, action, clause_locations in zip(clauses, actions, locations, strict=True)]


def target_pair_count(events: list[ExtractionSubEvent]) -> int:
    return sum(len(event.locations) for event in events)
