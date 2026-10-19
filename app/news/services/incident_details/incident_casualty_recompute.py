"""Single source-validated writer for incident casualty fields."""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.llm_knowledge.message_text import clean_message_text
from app.core.text_normalization import normalize_arabic_text
from app.llm.dtos import CasualtyCountEvidence, ExtractionCasualties
from app.news.models.duplicate_match import DuplicateMatch
from app.news.models.incident import Incident
from app.news.models.incident_detail import IncidentDetail
from app.news.models.incident_update import IncidentUpdate, UpdateAction
from app.news.models.raw_message import RawMessage
from app.news.models.village import Village
from app.news.models.village_location_alias import VillageLocationAlias
from app.news.services.incident_details.casualty_count_backstop import apply_casualty_count_backstop
from app.news.services.incident_details.casualty_gender_evidence import reject_unproven_demographics
from app.news.services.incident_details.casualty_merge_provenance import filter_validated_claims
from app.news.services.incident_details.casualty_text import (
    find_count_mentions,
    find_supporting_mention,
    has_casualty_wording,
    strip_page_header,
)

INCIDENT_FIELDS = ("deaths", "injuries", "total_deaths", "total_injuries")
DETAIL_FIELDS = ("male_d", "male_i", "female_d", "female_i", "children_d", "children_i")
FIELDS = INCIDENT_FIELDS + tuple(f"detail.{name}" for name in DETAIL_FIELDS)
REASON_CODES = frozenset({"created", "merged", "revision", "transition", "reconciled", "repair"})


@dataclass(frozen=True)
class ConnectedCasualtySource:
    raw_message_id: int
    text: str
    source: str | None
    received_at: object | None
    origin: str
    extraction_result: dict[str, Any] | None = None
    recorded_values: dict[str, Any] = field(default_factory=dict)
    match_result: dict[str, Any] | None = None


@dataclass(frozen=True)
class ValidatedCasualtyClaim:
    raw_message_id: int
    origin: str
    village_id: int
    village_name: str
    values: dict[str, int | None]
    quotes: dict[str, str]
    received_at: object | None = None
    owner_source: bool = False
    claim_id: str | None = None
    is_final_toll: bool = False
    is_health_ministry: bool = False


@dataclass(frozen=True)
class CasualtyValidationResult:
    claims: tuple[ValidatedCasualtyClaim, ...]
    source_ids: tuple[int, ...]
    sources_with_text: int
    sources_with_stored_values: int
    disproved_sources: int
    attributed_villages: tuple[str, ...]
    aggregate_quotes: tuple[str, ...] = ()
    conflict_reason: str | None = None
    approximate_quotes: tuple[str, ...] = ()
    provenance_rejections: tuple[dict[str, Any], ...] = ()


_SUBSET_MARKER_RE = re.compile(r"(?:من\s+بينهم|من\s+بينهما|بينهم|بينهما|منهم)")
_MINISTRY_INTRO_RE = re.compile(
    r"(?:صدر\s+عن\s+.*?وزار[ةه]\s+الصحة|"
    r"مركز\s+عمليات\s+طوارئ\s+الصحة|"
    r"وزار[ةه]\s+الصحة\s*:|"
    r"أعلنت?\s+وزار[ةه]\s+الصحة)",
    re.IGNORECASE
)


def _is_within_ministry_span(text: str, claim_text: str) -> bool:
    """Check if claim_text is within a Ministry introduction span in text."""
    # Find the Ministry introduction match
    match = _MINISTRY_INTRO_RE.search(text)
    if not match:
        return False

    # Find the claim in the text
    claim_pos = text.find(claim_text)
    if claim_pos < 0:
        return False

    # Ministry span ends at the end of the next sentence/clause or at the next main casualty count
    # For simplicity, we check if the claim starts within or immediately after the ministry intro
    ministry_start = match.start()
    # Look for the end of the ministry statement (next newline or semicolon, or next casualty count not in this span)
    ministry_end = match.end()
    # Extend the ministry span to the next sentence boundary
    next_boundary = min(
        [pos for pos in (text.find("\n", ministry_end), text.find("؛", ministry_end), text.find(".", ministry_end)) if pos > ministry_end],
        default=len(text)
    )

    # Claim is within ministry span if it starts before the boundary and after or at the start
    return ministry_start <= claim_pos < next_boundary


def _claim_units(text: str) -> list[tuple[str, str, dict[str, int | None], bool]]:
    """Return claim_id, text, values, and whether demographics supplied the main.

    Each exact main count owns only explicit demographic items after its own
    subset marker and before the next main claim.  Main counts are never copied
    into demographic fields.
    """
    units: list[tuple[str, str, dict[str, int | None], bool]] = []
    for clause_number, raw_clause in enumerate(re.split(r"[\n؛]+", text)):
        clause = raw_clause.strip()
        if not clause:
            continue
        mentions = list(find_count_mentions(clause))
        mains = [
            (index, mention)
            for index, mention in enumerate(mentions)
            if mention.kind in {"deaths", "injuries"}
            and mention.counts_total
        ]
        for ordinal, (mention_index, main) in enumerate(mains):
            values = {key: None for key in INCIDENT_FIELDS + DETAIL_FIELDS}
            values[main.kind] = main.value
            next_start = mains[ordinal + 1][1].anchor_start if ordinal + 1 < len(mains) else len(clause)
            marker = _SUBSET_MARKER_RE.search(clause, max(main.end, 0), next_start)
            if marker:
                for subset in mentions[mention_index + 1 :]:
                    # Mention offsets map back to the source while the marker
                    # regex runs on the raw clause; Arabic diacritics can make
                    # their end offsets differ by one.  Comparing with the
                    # marker start still proves the number follows the marker.
                    if subset.anchor_start <= marker.start() or subset.anchor_start >= next_start:
                        continue
                    if subset.gender_or_group not in {"male", "female", "children"}:
                        continue
                    # Only explicit demographic nouns are subset items. A
                    # casualty main that merely has a nearby group is excluded.
                    if subset.kind is not None and subset.counts_total:
                        continue
                    field_name = f"{subset.gender_or_group}_{'d' if main.kind == 'deaths' else 'i'}"
                    values[field_name] = subset.value
            claim_text = clause
            units.append((f"clause-{clause_number}-{main.kind}-{ordinal}", claim_text, values, False))

        if mains:
            continue
        demographics: dict[str, int] = {}
        for mention in mentions:
            if mention.gender_or_group in {"male", "female", "children"}:
                demographics[mention.gender_or_group] = mention.value
        if not demographics:
            continue
        kinds = [kind for kind in ("deaths", "injuries") if has_casualty_wording(clause, kind)]
        if len(kinds) != 1:
            continue
        kind = kinds[0]
        values = {key: None for key in INCIDENT_FIELDS + DETAIL_FIELDS}
        suffix = "d" if kind == "deaths" else "i"
        for group, value in demographics.items():
            values[f"{group}_{suffix}"] = value
        values[kind] = sum(demographics.values())
        units.append((f"clause-{clause_number}-{kind}-listed", clause, values, True))
    return units


def connected_casualty_sources(db: Session, incident: Incident) -> list[ConnectedCasualtySource]:
    ids = {incident.raw_message_id} if incident.raw_message_id else set()
    snapshots: dict[int, ConnectedCasualtySource] = {}
    for match in db.scalars(select(DuplicateMatch).where(or_(DuplicateMatch.incident_id == incident.id, DuplicateMatch.matched_incident_id == incident.id))):
        if match.raw_message_id:
            ids.add(match.raw_message_id)
    for update in db.scalars(select(IncidentUpdate).where(IncidentUpdate.incident_id == incident.id)):
        values = update.new_values or {}
        merged = values.get("merged_from")
        if isinstance(merged, dict) and isinstance(merged.get("raw_message_id"), int) and isinstance(merged.get("khabar"), str):
            raw_id = merged["raw_message_id"]
            ids.add(raw_id)
            recorded = {key: values.get(key) for key in INCIDENT_FIELDS}
            recorded.update({key: values.get(f"detail.{key}") for key in DETAIL_FIELDS})
            snapshots[raw_id] = ConnectedCasualtySource(raw_id, merged["khabar"], merged.get("channel"), update.created_at, "merged_from_snapshot", None, recorded)
    live = {raw.id: raw for raw in db.scalars(select(RawMessage).where(RawMessage.id.in_(ids)))} if ids else {}
    sources = [ConnectedCasualtySource(raw.id, raw.raw_text or "", str(raw.source_id) if raw.source_id else raw.source_name, raw.received_at, "raw_messages", raw.extraction_result if isinstance(raw.extraction_result, dict) else None, {}, raw.match_result if isinstance(raw.match_result, dict) else None) for raw in live.values()]
    sources.extend(snapshot for raw_id, snapshot in snapshots.items() if raw_id not in live)
    return sorted(sources, key=lambda item: (str(item.received_at), item.raw_message_id))


def derived_total(*values: int | None) -> int | None:
    present = [value for value in values if isinstance(value, int) and not isinstance(value, bool)]
    return max(present) if present else None


def demographic_total(*values: int | None) -> int | None:
    present = [value for value in values if isinstance(value, int) and not isinstance(value, bool)]
    return sum(present) if present else None


def _village_catalog(db: Session) -> list[tuple[str, int, str]]:
    aliases: list[tuple[str, int, str]] = []
    for village in db.scalars(select(Village)):
        label = village.ref_name_en or village.ref_name_ar or village.cad_name or str(village.id)
        for candidate in (village.ref_name_ar, village.ref_name_en, village.cad_name, village.acs_name):
            if candidate:
                aliases.append((normalize_arabic_text(candidate), village.id, label))
    for alias, village in db.execute(select(VillageLocationAlias, Village).join(Village, Village.id == VillageLocationAlias.village_id).where(VillageLocationAlias.is_active.is_(True))):
        label = village.ref_name_en or village.ref_name_ar or village.cad_name or str(village.id)
        aliases.append((normalize_arabic_text(alias.alias_text), village.id, label))
    return sorted(aliases, key=lambda item: len(item[0]), reverse=True)


_ARABIC_TOKEN_RE = re.compile(r"[\u0600-\u06ff]+")
_CLAUSE_BREAK_RE = re.compile(
    r"[\n\r؛,،!?؟•●▪📌|]+|\bLink\b|"
    r"\s+و(?=(?:ال)?(?:شهيد|شهيدان|شهداء|جريح|جريحان|جرحى|اصاب(?:ه|ات))\b)|"
    r"(?<!\.)\.(?!\.)(?=\s|$)"
)
_ATTACHED_LOCATION_PREFIXES = ("و", "ب", "ل", "ف")
_NON_TARGET_QUALIFIERS = frozenset({"قضاء", "منطقه", "وادي"})
_LOCATION_CONTEXT = frozenset({"بلده", "قريه", "في", "علي", "من", "نحو", "باتجاه"})
_COMMON_LOCATION_STARTS = frozenset({"حدث", "عمره", "النبي", "عين", "دير", "كفر", "تل", "جبل"})
_REGION_PHRASES = frozenset({"جنوب لبنان", "جنوبي لبنان", "جبل عامل", "في القضاء نفسه"})


def _arabic_tokens(text: str) -> list[tuple[str, int, int]]:
    normalized = normalize_arabic_text(text)
    return [(match.group(0), match.start(), match.end()) for match in _ARABIC_TOKEN_RE.finditer(normalized)]


def _token_matches(token: str, expected: str, *, first: bool) -> bool:
    if token == expected:
        return True
    if first:
        variants = {token}
        for _ in range(2):
            variants.update(value[1:] for value in tuple(variants) if value[:1] in _ATTACHED_LOCATION_PREFIXES and len(value) > 1)
            variants.update(value[2:] for value in tuple(variants) if value.startswith("ال") and len(value) > 2)
        if expected in variants or expected.removesuffix("ه") in variants:
            return True
    return token.removesuffix("ه") == expected.removesuffix("ه")


def _qualifier_catalog(db: Session) -> frozenset[str]:
    names = set(_REGION_PHRASES)
    for caza, mohafaza in db.execute(select(Village.caza_ar, Village.mohafaza_ar)).unique():
        for value in (caza, mohafaza):
            if value:
                names.add(normalize_arabic_text(value))
    return frozenset(names)


def _requires_location_context(alias_tokens: list[str]) -> bool:
    return len(alias_tokens) == 1 and (
        len(alias_tokens[0].removeprefix("ال")) < 4
        or alias_tokens[0] in _COMMON_LOCATION_STARTS
    )


def village_mentions(
    text: str,
    aliases: list[tuple[str, int, str]],
    qualifier_names: frozenset[str] = frozenset(),
) -> list[tuple[int, int, int, str]]:
    """Whole-token gazetteer matches as ``(start, end, id, label)``.

    Results are non-overlapping and longest-first at the same token, which
    prevents Riha/Bsalim-style matches inside longer Arabic words or names.
    """
    tokens = _arabic_tokens(text)
    normalized_text = normalize_arabic_text(text)
    qualifier_spans: list[tuple[int, int]] = []
    for qualifier in qualifier_names | _REGION_PHRASES:
        cursor = 0
        while (at := normalized_text.find(qualifier, cursor)) >= 0:
            before = normalized_text[:at]
            if qualifier in _REGION_PHRASES or re.search(r"(?:قضاء|منطقه)\s*$", before) or re.search(r"[-–—]\s*$", before):
                qualifier_spans.append((at, at + len(qualifier)))
            cursor = at + max(1, len(qualifier))
    candidates: list[tuple[int, int, int, int, int, str]] = []
    for alias, village_id, label in aliases:
        alias_tokens = [item[0] for item in _arabic_tokens(alias)]
        if not alias_tokens or not any("\u0600" <= char <= "\u06ff" for char in alias):
            continue
        if len(alias_tokens) > 1:
            compact_aliases = {"".join(alias_tokens), "".join(value.removeprefix("ال") for value in alias_tokens)}
            for index, token in enumerate(tokens):
                if any(_token_matches(token[0], compact_alias, first=True) for compact_alias in compact_aliases):
                    previous = tokens[index - 1][0] if index else ""
                    if previous in _NON_TARGET_QUALIFIERS:
                        continue
                    candidates.append((index, -len(alias_tokens), token[1], token[2], village_id, label))
        for index in range(0, len(tokens) - len(alias_tokens) + 1):
            window = tokens[index:index + len(alias_tokens)]
            if not all(_token_matches(token[0], expected, first=offset == 0) for offset, (token, expected) in enumerate(zip(window, alias_tokens))):
                continue
            previous = tokens[index - 1][0] if index else ""
            following = tokens[index + len(alias_tokens)][0] if index + len(alias_tokens) < len(tokens) else ""
            if previous in _NON_TARGET_QUALIFIERS:
                continue
            if len(alias_tokens) == 1 and (previous in {"هذا", "ذلك"} or following == "اليوم"):
                continue
            if _requires_location_context(alias_tokens) and previous not in _LOCATION_CONTEXT:
                continue
            candidates.append((index, -len(alias_tokens), window[0][1], window[-1][2], village_id, label))
        # Gazetteer forms commonly append the caza ("ريحانة جزين") while news
        # copy writes it as "الريحان قضاء جزين". Match that complete sequence;
        # the caza token alone remains excluded by the qualifier rule above.
        if len(alias_tokens) >= 2:
            for index in range(0, len(tokens) - len(alias_tokens)):
                window = tokens[index:index + len(alias_tokens) + 1]
                if window[-2][0] != "قضاء":
                    continue
                compared = window[:-2] + window[-1:]
                if all(_token_matches(token[0], expected, first=offset == 0) for offset, (token, expected) in enumerate(zip(compared, alias_tokens))):
                    candidates.append((index, -(len(alias_tokens) + 1), window[0][1], window[-1][2], village_id, label))
    selected: list[tuple[int, int, int, str]] = []
    occupied: set[int] = set()
    for index, negative_length, start, end, village_id, label in sorted(candidates):
        token_indexes = set(range(index, index - negative_length))
        if occupied & token_indexes:
            continue
        if any(span_start <= start and end <= span_end for span_start, span_end in qualifier_spans):
            continue
        normalized_name = normalize_arabic_text(text[start:end])
        prefix = normalize_arabic_text(text[:start])
        if normalized_name in _REGION_PHRASES:
            continue
        if normalized_name in qualifier_names and (
            re.search(r"(?:قضاء|منطقه)\s*$", prefix)
            or (re.search(r"[-–—]\s*$", text[:start]) and selected)
        ):
            continue
        occupied.update(token_indexes)
        selected.append((start, end, village_id, label))
    return selected


def _claim_clause(text: str, quote: str) -> str:
    """Return the line/bullet clause containing evidence, capped for the API."""
    quote = (quote or "").strip()
    # A previous evidence pass may already have produced the bounded clause.
    # Re-windowing that 200-character span can cut off a location at its end.
    if len(quote) >= 190 and quote in text:
        return quote[:200]
    at = text.find(quote) if quote else -1
    if at < 0:
        return quote[:200]
    start = 0
    end = len(text)
    for match in _CLAUSE_BREAK_RE.finditer(text):
        if match.end() <= at:
            start = match.end()
        elif match.start() >= at + len(quote):
            end = match.start()
            break
    clause = text[start:end].strip(" \t-–—:،")
    clause = re.split(r"(?:─{3,}|\shttps?://|\s(?:قناة|Channel)\b|\n)", clause, maxsplit=1)[0].rstrip()
    if len(clause) <= 200:
        return clause
    relative = at - start
    left = max(0, min(relative - 80, len(clause) - 200))
    return clause[left:left + 200].strip()


def _line_label_owner(
    text: str,
    quote: str,
    aliases: list[tuple[str, int, str]],
    qualifier_names: frozenset[str],
) -> tuple[int, str] | None:
    """A leading ``X:`` label owns every casualty claim on that list line."""
    at = text.find(quote) if quote else -1
    if at < 0:
        return None
    mentions = [item for item in find_count_mentions(quote) if item.kind]
    if mentions:
        mention_at = text.find(mentions[0].text, at)
        if mention_at >= 0:
            at = mention_at
    prefix = text[:at]
    candidates: list[tuple[int, tuple[int, str]]] = []
    for marker in re.finditer(r"(?:^|[\n•▪●]|\s[-–—]\s+)\s*([^:\n]{1,100})[:：]", prefix):
        label = marker.group(1).strip(" \t-–—▪●📌")
        matches = village_mentions(label, aliases, qualifier_names)
        if matches:
            chosen = matches[-1]
            candidates.append((marker.end(), (chosen[2], chosen[3])))
    return max(candidates, default=(0, None), key=lambda item: item[0])[1]


def _source_target_ids(source: ConnectedCasualtySource | None) -> list[int]:
    if not source or not source.match_result:
        return []
    ids = []
    for match in source.match_result.get("village_matches", []):
        village_id = match.get("matched_village_id")
        role = match.get("village_role", "target")
        if isinstance(village_id, int) and role == "target" and village_id not in ids:
            ids.append(village_id)
    return ids


def _attributed_village(
    text: str,
    quote: str,
    aliases: list[tuple[str, int, str]],
    source: ConnectedCasualtySource | None = None,
    *,
    qualifier_names: frozenset[str] = frozenset(),
    incident_village_id: int | None = None,
) -> tuple[int, str] | None:
    labelled = _line_label_owner(text, quote, aliases, qualifier_names)
    if labelled is not None:
        return labelled
    # A bulletin bullet with an explicit but unresolved place label must never
    # inherit the incident village merely because that incident is one of the
    # source targets.  It is safer to keep the claim unattributed for review.
    if re.match(r"^\s*[-•▪●]\s*[^:\n]{1,100}:\s*", quote):
        return None
    clause = _claim_clause(text, quote)
    matches = village_mentions(clause, aliases, qualifier_names)
    if matches:
        distinct_ids = {item[2] for item in matches}
        if len(distinct_ids) > 1:
            normalized = normalize_arabic_text(clause)
            event_markers = tuple(re.finditer(r"(?:غاره|استهداف|استهدفت|قصف|اعتداء)", normalized))
            if event_markers:
                event_at = event_markers[-1].end()
                event_matches = [item for item in matches if item[0] >= event_at]
                hometown_matches = [
                    item for item in matches
                    if re.search(r"من\s+بلده\s*$", normalized[:item[0]])
                ]
                if event_matches and hometown_matches:
                    matches = event_matches
                    distinct_ids = {item[2] for item in matches}
            if len(distinct_ids) > 1 and re.search(r"(?:طريق|اوتوستراد|مسلك)", normalized):
                preferred_ids = [incident_village_id, *_source_target_ids(source)]
                chosen = next((item for village_id in preferred_ids if village_id is not None for item in matches if item[2] == village_id), None)
                if chosen is not None:
                    return chosen[2], chosen[3]
            if len(distinct_ids) > 1:
                return None
        mentions = find_count_mentions(clause)
        count_text = next((mention.text for mention in mentions if mention.kind), quote)
        quote_at = normalize_arabic_text(clause).find(normalize_arabic_text(count_text))
        preceding = [item for item in matches if item[0] <= quote_at] if quote_at >= 0 else matches
        chosen = max(preceding, key=lambda item: item[0]) if preceding else min(matches, key=lambda item: item[0])
        return chosen[2], chosen[3]
    target_ids = _source_target_ids(source)
    # A location elsewhere in the source but outside this clause is not proof
    # that it owns the count when the source names several places. A single
    # unambiguous source target can bridge an adjacent comma clause.
    source_mentions = village_mentions(text, aliases, qualifier_names)
    mentioned_ids = {item[2] for item in source_mentions}
    if len(target_ids) == 1 and len(mentioned_ids) <= 1 and source and source.match_result:
        raw_targets = [
            item.get("raw_village_text")
            for item in source.match_result.get("village_matches", [])
            if item.get("matched_village_id") == target_ids[0]
            and item.get("village_role", "target") == "target"
        ]
        normalized_source = normalize_arabic_text(text)
        if any(
            isinstance(raw_target, str)
            and normalize_arabic_text(raw_target) in normalized_source
            for raw_target in raw_targets
        ):
            village_id = target_ids[0]
            label = next((label for _, candidate_id, label in aliases if candidate_id == village_id), str(village_id))
            return village_id, label
    if len(mentioned_ids) == 1:
        village_id = next(iter(mentioned_ids))
        label = next(item[3] for item in source_mentions if item[2] == village_id)
        return village_id, label
    if len(target_ids) == 1 and (not mentioned_ids or mentioned_ids == set(target_ids)):
        village_id = target_ids[0]
        label = next((label for _, candidate_id, label in aliases if candidate_id == village_id), str(village_id))
        return village_id, label
    return None


def _clean_evidence(text: str, field_name: str, value: int, preferred: str | None = None) -> str | None:
    mention = find_supporting_mention(preferred, field_name, value) if preferred else None
    seed = mention.text if mention is not None else None
    if seed is None:
        mention = find_supporting_mention(text, field_name, value)
        seed = mention.text if mention is not None else None
    if not seed:
        return None
    clause = _claim_clause(text, seed)
    return clause if find_supporting_mention(clause, field_name, value) else seed[:200]


def _is_subset_breakdown(span: str, value: int) -> bool:
    normalized = normalize_arabic_text(span)
    return bool(re.search(rf"(?:من\s+بينهم|بينهم|منهم)\s+{value}(?!\d)", normalized))


def _candidate_values(source: ConnectedCasualtySource) -> tuple[ExtractionCasualties | None, list[CasualtyCountEvidence], list[dict[str, Any]]]:
    payload = source.extraction_result or {}
    block = payload.get("casualties") if isinstance(payload, dict) else None
    if isinstance(block, dict):
        evidence = [CasualtyCountEvidence.model_validate(item) for item in payload.get("casualty_evidence", []) if isinstance(item, dict)]
        return ExtractionCasualties.model_validate(block), evidence, [item for item in payload.get("village_roles", []) if isinstance(item, dict)]
    values = source.recorded_values
    if any(isinstance(values.get(key), int) for key in INCIDENT_FIELDS + DETAIL_FIELDS):
        return ExtractionCasualties.model_validate({
            "deaths": values.get("deaths"), "injuries": values.get("injuries"), "total_deaths": values.get("total_deaths"), "total_injuries": values.get("total_injuries"),
            "male_deaths": values.get("male_d"), "male_injuries": values.get("male_i"), "female_deaths": values.get("female_d"), "female_injuries": values.get("female_i"),
            "children_deaths": values.get("children_d"), "children_injuries": values.get("children_i"),
        }), [], []
    return None, [], []


def validate_incident_casualty_sources(db: Session, incident: Incident) -> CasualtyValidationResult:
    sources, aliases = connected_casualty_sources(db, incident), _village_catalog(db)
    qualifier_names = _qualifier_catalog(db)
    claims: list[ValidatedCasualtyClaim] = []
    aggregate_quotes: list[str] = []
    approximate_quotes: list[str] = []
    stored_sources = disproved = 0
    cleaned_by_source: dict[int, str] = {}
    for source in sources:
        casualties, evidence, roles = _candidate_values(source)
        if not source.text.strip():
            continue
        cleaned = strip_page_header(clean_message_text(source.text))
        cleaned_by_source[source.raw_message_id] = cleaned
        approximate_quotes.extend(_approximate_casualty_phrases(cleaned))
        # A shared bulletin toll must remain reviewable even when the retained
        # snapshot/extraction block has no usable structured casualty values.
        for mention in find_count_mentions(cleaned):
            if not mention.kind or not mention.counts_total:
                continue
            clause = _claim_clause(cleaned, mention.text)
            if len({item[2] for item in village_mentions(clause, aliases, qualifier_names)}) > 1:
                aggregate_quotes.append(clause)
        deterministic_units = _claim_units(cleaned)
        if deterministic_units:
            if casualties is not None:
                stored_sources += 1
            for unit_id, claim_text, values, _filled_from_people in deterministic_units:
                attributed = _attributed_village(
                    cleaned,
                    claim_text,
                    aliases,
                    source,
                    qualifier_names=qualifier_names,
                    incident_village_id=incident.village_id,
                )
                if attributed is None:
                    aggregate_quotes.append(claim_text)
                    continue
                quotes = {key: claim_text for key, value in values.items() if value is not None}
                normalized_claim = normalize_arabic_text(claim_text)
                claims.append(ValidatedCasualtyClaim(
                    source.raw_message_id,
                    source.origin,
                    attributed[0],
                    attributed[1],
                    values,
                    quotes,
                    source.received_at,
                    source.raw_message_id == incident.raw_message_id,
                    claim_id=f"{source.raw_message_id}:{unit_id}",
                    is_final_toll="حصيله نهائيه" in normalized_claim,
                    is_health_ministry=_is_within_ministry_span(cleaned, claim_text),
                ))
            continue
        if casualties is None:
            continue
        stored_sources += 1
        guarded, kept = apply_casualty_count_backstop(cleaned, casualties, evidence, raw_message_id=source.raw_message_id)
        guarded = reject_unproven_demographics(cleaned, guarded)
        kept_by_field = {item.field: item.evidence_span for item in kept}
        before, after = casualties.model_dump(mode="python"), guarded.model_dump(mode="python")
        if any(before.get(key) is not None and after.get(key) is None for key in before):
            disproved += 1
        for role in roles:
            quote = role.get("evidence_span")
            if not isinstance(quote, str) or quote not in cleaned:
                continue
            claim_span = _claim_clause(cleaned, quote)
            attributed = _attributed_village(cleaned, quote, aliases, source, qualifier_names=qualifier_names, incident_village_id=incident.village_id)
            values = {key: None for key in INCIDENT_FIELDS + DETAIL_FIELDS}
            for key in ("deaths", "injuries"):
                value = role.get(key)
                if isinstance(value, int) and find_supporting_mention(claim_span, key, value) and not _is_subset_breakdown(claim_span, value):
                    values[key] = value
            if any(value is not None for value in values.values()):
                if attributed is None:
                    aggregate_quotes.append(claim_span)
                else:
                    claims.append(ValidatedCasualtyClaim(source.raw_message_id, source.origin, attributed[0], attributed[1], values, {key: claim_span for key, value in values.items() if value is not None}, source.received_at, source.raw_message_id == incident.raw_message_id))
        field_map = {"deaths": "deaths", "injuries": "injuries", "total_deaths": "deaths", "total_injuries": "injuries", "male_deaths": "male_d", "male_injuries": "male_i", "female_deaths": "female_d", "female_injuries": "female_i", "children_deaths": "children_d", "children_injuries": "children_i"}
        grouped: dict[int, tuple[str, dict[str, int | None], dict[str, str]]] = {}
        for extraction_field, output_field in field_map.items():
            value = after.get(extraction_field)
            if not isinstance(value, int):
                continue
            mention = find_supporting_mention(cleaned, extraction_field, value)
            quote = _clean_evidence(cleaned, extraction_field, value, kept_by_field.get(extraction_field))
            if not quote or _is_subset_breakdown(quote, value):
                continue
            attributed = _attributed_village(cleaned, quote, aliases, source, qualifier_names=qualifier_names, incident_village_id=incident.village_id)
            if attributed is None:
                aggregate_quotes.append(quote)
                continue
            _, values, quotes = grouped.setdefault(attributed[0], (attributed[1], {key: None for key in INCIDENT_FIELDS + DETAIL_FIELDS}, {}))
            values[output_field], quotes[output_field] = value, quote

        # Deterministically recover explicit demographic subsets even when the
        # model omitted them.  A grammatical casualty noun never supplies the
        # group: find_count_mentions only labels explicit طفل/سيدة/رجل nouns.
        mentions = list(find_count_mentions(cleaned))
        for index, mention in enumerate(mentions):
            group = mention.gender_or_group
            if group not in {"male", "female", "children"}:
                continue
            claim_span = _claim_clause(cleaned, mention.text)
            kind = mention.kind
            if kind is None:
                at = cleaned.find(mention.text)
                preceding = [
                    candidate
                    for candidate in mentions[:index]
                    if candidate.kind in {"deaths", "injuries"}
                    and candidate.counts_total
                    and cleaned.find(candidate.text) <= at
                    and candidate.text in claim_span
                ]
                if preceding:
                    kind = preceding[-1].kind
                else:
                    kinds = {
                        candidate.kind
                        for candidate in find_count_mentions(claim_span)
                        if candidate.kind in {"deaths", "injuries"}
                    }
                    kind = next(iter(kinds)) if len(kinds) == 1 else None
            if kind not in {"deaths", "injuries"}:
                continue
            attributed = _attributed_village(
                cleaned,
                mention.text,
                aliases,
                source,
                qualifier_names=qualifier_names,
                incident_village_id=incident.village_id,
            )
            if attributed is None:
                continue
            _, values, quotes = grouped.setdefault(
                attributed[0],
                (attributed[1], {key: None for key in INCIDENT_FIELDS + DETAIL_FIELDS}, {}),
            )
            output_field = f"{group}_{'d' if kind == 'deaths' else 'i'}"
            values[output_field] = mention.value
            quotes[output_field] = claim_span
        for village_id, (label, values, quotes) in grouped.items():
            claims.append(ValidatedCasualtyClaim(source.raw_message_id, source.origin, village_id, label, values, quotes, source.received_at, source.raw_message_id == incident.raw_message_id))
        # Recover one rejected main total when the source has a nearby explicit
        # main count. This repairs ``11 injured ... among them 4 children``
        # without importing every headline/revision count from a long story.
        references = [
            cleaned.find(span) for span in (
                *kept_by_field.values(),
                *(role.get("evidence_span") for role in roles if isinstance(role.get("evidence_span"), str)),
            )
            if span and cleaned.find(span) >= 0
        ]
        for kind in ("deaths", "injuries"):
            if isinstance(after.get(kind), int) or not isinstance(before.get(kind), int) or not references:
                continue
            candidates = []
            for mention in find_count_mentions(cleaned):
                if mention.kind != kind or not mention.counts_total:
                    continue
                claim_span = _claim_clause(cleaned, mention.text)
                if _is_subset_breakdown(claim_span, mention.value):
                    continue
                at = cleaned.find(mention.text)
                candidates.append((min(abs(at - ref) for ref in references), at, mention, claim_span))
            if not candidates:
                continue
            _, _, mention, claim_span = min(candidates, key=lambda item: (item[0], item[1]))
            attributed = _attributed_village(cleaned, mention.text, aliases, source, qualifier_names=qualifier_names, incident_village_id=incident.village_id)
            if attributed is None:
                aggregate_quotes.append(claim_span)
                continue
            values = {key: None for key in INCIDENT_FIELDS + DETAIL_FIELDS}
            values[kind] = mention.value
            claims.append(ValidatedCasualtyClaim(source.raw_message_id, source.origin, attributed[0], attributed[1], values, {kind: claim_span}, source.received_at, source.raw_message_id == incident.raw_message_id))
    # Merge provenance guard: a claim is kept only if its quote is in the cleaned
    # body of its own source and not on a header/memorial line.
    claims, provenance_rejections = filter_validated_claims(claims, cleaned_by_source)
    return CasualtyValidationResult(tuple(claims), tuple(source.raw_message_id for source in sources), sum(bool(source.text.strip()) for source in sources), stored_sources, disproved, tuple(sorted({claim.village_name for claim in claims})), tuple(dict.fromkeys(aggregate_quotes)), approximate_quotes=tuple(dict.fromkeys(approximate_quotes)), provenance_rejections=tuple(provenance_rejections))


_APPROXIMATE_RE = re.compile(
    r"(?:اكثر\s+من|أكثر\s+من|نحو|حوالي|قرابه|قرابة|ما\s+لا\s+يقل\s+عن)\s+"
    r"[0-9٠-٩]+\s+(?:شهيد\w*|ضحي\w*|قتيل\w*|جريح\w*|مصاب\w*)|"
    r"عشرات\s+(?:الشهداء|الضحايا|القتلى|الجرحى|المصابين)"
)


def _approximate_casualty_phrases(text: str) -> list[str]:
    normalized = normalize_arabic_text(text)
    return [match.group(0) for match in _APPROXIMATE_RE.finditer(normalized)]


def _claim_priority(claim: ValidatedCasualtyClaim) -> tuple[int, int, str, int]:
    return (
        int(claim.is_final_toll),
        int(claim.is_health_ministry),
        str(claim.received_at or ""),
        claim.raw_message_id,
    )


def resolve_casualty_selection(
    result: CasualtyValidationResult,
    village_id: int | None,
) -> tuple[dict[str, int | None], str | None, dict[str, dict[str, Any]]]:
    values = {key: None for key in INCIDENT_FIELDS + DETAIL_FIELDS}
    relevant = [claim for claim in result.claims if claim.village_id == village_id]
    conflicts: list[str] = []
    selection: dict[str, dict[str, Any]] = {}

    # K2 rule: Deaths and injuries may come from different claims only if no single
    # claim states both. When a source has both deaths and injuries (across claims),
    # prefer that source to avoid splitting claims between sources.

    # Group claims by source to find sources with both sides
    sources_by_id = {}
    for claim in relevant:
        if claim.raw_message_id not in sources_by_id:
            sources_by_id[claim.raw_message_id] = []
        sources_by_id[claim.raw_message_id].append(claim)

    # Find sources that have both deaths and injuries claims
    sources_with_both = {
        sid: claims for sid, claims in sources_by_id.items()
        if any(isinstance(c.values.get("deaths"), int) for c in claims)
        and any(isinstance(c.values.get("injuries"), int) for c in claims)
    }

    # Check which sides have any candidates
    has_deaths = any(isinstance(c.values.get("deaths"), int) for c in relevant)
    has_injuries = any(isinstance(c.values.get("injuries"), int) for c in relevant)

    # Pick a unified source if both sides exist and a source has both
    chosen_unified_source = None
    if sources_with_both and has_deaths and has_injuries:
        # Pick the best source (highest priority among sources with both)
        best_source_claims = max(sources_with_both.values(), key=lambda claims: _claim_priority(max(claims, key=_claim_priority)))
        chosen_unified_source = best_source_claims[0].raw_message_id

    for base, total, detail_fields in (
        ("deaths", "total_deaths", ("male_d", "female_d", "children_d")),
        ("injuries", "total_injuries", ("male_i", "female_i", "children_i")),
    ):
        candidates = [
            claim for claim in relevant
            if isinstance(claim.values.get(base), int)
            or demographic_total(*(claim.values.get(field) for field in detail_fields)) is not None
        ]
        if not candidates:
            continue

        claim_value = lambda claim: claim.values.get(base) if isinstance(claim.values.get(base), int) else demographic_total(*(claim.values.get(field) for field in detail_fields))
        distinct = sorted({claim_value(claim) for claim in candidates})
        if len(distinct) > 1:
            conflicts.append(f"conflicting {base}: {' vs '.join(map(str, distinct))}")

        # Prefer a claim from the unified source if available, otherwise pick best candidate
        if chosen_unified_source:
            # Filter candidates to only those from the unified source
            unified_candidates = [c for c in candidates if c.raw_message_id == chosen_unified_source]
            if unified_candidates:
                chosen = max(unified_candidates, key=_claim_priority)
            else:
                # Unified source doesn't have this side, pick best overall
                chosen = max(candidates, key=_claim_priority)
        else:
            chosen = max(candidates, key=_claim_priority)
        values[base] = claim_value(chosen)
        values[total] = claim_value(chosen)
        for field_name in detail_fields:
            values[field_name] = chosen.values.get(field_name)
        reason = "final_toll" if chosen.is_final_toll else "health_ministry" if chosen.is_health_ministry else "latest_message"
        selection[base] = {
            "claim_id": chosen.claim_id or f"{chosen.raw_message_id}:legacy",
            "source_id": chosen.raw_message_id,
            "claim_text": chosen.quotes.get(base) or next(iter(chosen.quotes.values()), ""),
            "selection_rule": reason,
            "competing_claims": [
                {
                    "claim_id": claim.claim_id or f"{claim.raw_message_id}:legacy",
                    "source_id": claim.raw_message_id,
                    "value": claim_value(claim),
                    "claim_text": claim.quotes.get(base) or next(iter(claim.quotes.values()), ""),
                }
                for claim in candidates
                if claim is not chosen
            ],
        }
        listed = demographic_total(*(values[field] for field in detail_fields))
        if listed is not None and values[total] is not None and listed > values[total]:
            conflicts.append(f"{total} below explicit demographic sum: {values[total]} < {listed}")
            for field in detail_fields:
                values[field] = None
    return values, "; ".join(conflicts) or None, selection


def resolved_casualty_values(result: CasualtyValidationResult, village_id: int | None) -> tuple[dict[str, int | None], str | None]:
    values, conflict, _selection = resolve_casualty_selection(result, village_id)
    return values, conflict


def _admin_edited(db: Session, incident: Incident) -> bool:
    statement = select(IncidentUpdate.new_values).where(IncidentUpdate.incident_id == incident.id, IncidentUpdate.action == UpdateAction.edit, IncidentUpdate.performed_by.is_not(None))
    result = db.execute(statement) if hasattr(db, "execute") else None
    edited = result.scalars().all() if result is not None and hasattr(result, "scalars") else db.scalars(statement).all() if hasattr(db, "scalars") else []
    return any(isinstance(item, dict) and set(item) & set(FIELDS) for item in edited)


def recompute_incident_casualties(db: Session, incident: Incident, *, raw_message_ids: list[int] | None = None, reason_code: str = "reconciled", creating: bool = False, audit_values: dict[str, Any] | None = None, validation: CasualtyValidationResult | None = None) -> bool:
    """Replace all incident/detail casualty fields with validated source values."""
    if reason_code not in REASON_CODES:
        raise ValueError(f"unsupported automatic casualty reason_code: {reason_code!r}")
    # Unit-level repository/materialization stubs cannot load source records.
    # They may exercise their caller's behavior, but must never make the writer
    # fall back to the incident's already-materialized casualty columns.
    if validation is None and not isinstance(db, Session):
        return False
    if _admin_edited(db, incident):
        return False
    validation = validation or validate_incident_casualty_sources(db, incident)
    new, conflict, selection = resolve_casualty_selection(validation, incident.village_id)
    detail = db.get(IncidentDetail, incident.id) if hasattr(db, "get") else None
    if not isinstance(detail, IncidentDetail):
        detail = None
    old = {key: getattr(incident, key, None) for key in INCIDENT_FIELDS}
    old.update({f"detail.{key}": getattr(detail, key, None) if detail else None for key in DETAIL_FIELDS})
    for key in INCIDENT_FIELDS:
        setattr(incident, key, new[key])
    if detail is not None:
        for key in DETAIL_FIELDS:
            setattr(detail, key, new[key])
    own_claim = any(claim.village_id == incident.village_id for claim in validation.claims)
    if validation.claims and not own_claim:
        incident.verification_status = "needs_verification"
        incident.verification_reason = f"casualty numbers in the source belong to: {', '.join(validation.attributed_villages)} — not this village"
    elif conflict:
        incident.verification_status, incident.verification_reason = "needs_verification", conflict
    elif validation.approximate_quotes:
        incident.verification_status = "needs_verification"
        incident.verification_reason = "approximate casualty count: " + " | ".join(validation.approximate_quotes)
    updated = {key: getattr(incident, key, None) for key in INCIDENT_FIELDS}
    updated.update({f"detail.{key}": getattr(detail, key, None) if detail else None for key in DETAIL_FIELDS})
    if old == updated and not creating:
        return False
    payload: dict[str, Any] = {**updated, "reason_code": "created" if creating else reason_code, "raw_message_ids": list(validation.source_ids or raw_message_ids or []), **(audit_values or {})}
    if selection:
        payload["chosen_casualty_claims"] = selection
    if conflict:
        payload["conflict_reason"] = conflict
    if validation.approximate_quotes:
        payload["approximate_casualty_evidence"] = list(validation.approximate_quotes)
    if validation.provenance_rejections:
        payload["casualty_provenance_rejected"] = list(validation.provenance_rejections)
    db.add(IncidentUpdate(incident_id=incident.id, action=UpdateAction.create if creating else UpdateAction.pipeline_merge, old_values=old, new_values=payload))
    return True
