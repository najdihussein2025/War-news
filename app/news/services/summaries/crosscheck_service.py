"""Add-only LLM cross-check for summary bulletins.

The deterministic parser stays authoritative. A larger model only proposes
(header, location, evidence) pairs the parser missed; every proposal is re-checked
in code before it can become an item:

* ``evidence_span`` must be a verbatim substring of the message, and must contain
  the location (so a village that is not written in the text can never get in);
* the header must resolve through the header dictionary (YAML, then learned
  mappings), otherwise it goes to the review task as ``unknown_header``;
* the location must resolve through the same strict parser/gazetteer, otherwise it
  goes to the review task as ``unresolved_location``;
* a duplicate of a parser item is dropped.

Nothing the model returns can remove or modify a parser item: the function only
returns additions. A timeout, bad JSON or connection error skips the cross-check.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.core.config import settings
from app.core.llm_knowledge.prompt_assembly import build_stage_system_prompt
from app.core.ollama_client import OllamaChatClient, OllamaChatMessage

from .dtos import ParsedSummaryItem
from .gazetteer import GazetteerSnapshot
from .headers import HeaderDictionarySnapshot
from .lexicon import LEXICON
from .normalize import normalize_token
from .parser import parse_summary

logger = logging.getLogger(__name__)

STAGE = "summary_crosscheck"
MAX_PROPOSALS = 40
MISSES_PATH = Path(__file__).resolve().parents[3] / "core" / "llm_knowledge" / "eval" / "summary_parser_misses.jsonl"
RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "missing": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "header": {"type": "string"},
                    "location": {"type": "string"},
                    "evidence_span": {"type": "string"},
                },
                "required": ["header", "location", "evidence_span"],
            },
        }
    },
    "required": ["missing"],
}


@dataclass(frozen=True)
class ParserPair:
    """A (header, location) pair the parser already extracted (read-only context)."""

    header: str
    location: str
    condition_id: int | None = None
    primary_village_id: int | None = None
    secondary_village_id: int | None = None


@dataclass(frozen=True)
class AcceptedAddition:
    header: str
    location: str
    evidence_span: str
    item: ParsedSummaryItem


@dataclass(frozen=True)
class ReviewAddition:
    reason: str  # unknown_header | unresolved_location
    header: str
    location: str
    evidence_span: str


@dataclass
class CrosscheckResult:
    accepted: list[AcceptedAddition] = field(default_factory=list)
    review: list[ReviewAddition] = field(default_factory=list)
    dropped: dict[str, int] = field(default_factory=dict)
    error: str | None = None
    called: bool = False

    def drop(self, reason: str) -> None:
        self.dropped[reason] = self.dropped.get(reason, 0) + 1


def build_crosscheck_client() -> OllamaChatClient:
    return OllamaChatClient(
        base_url=settings.ollama_base_url,
        api_key=settings.ollama_api_key,
        model=settings.summary_crosscheck_model,
        timeout_seconds=settings.summary_crosscheck_timeout_seconds,
    )


def build_messages(raw_text: str, pairs: Sequence[ParserPair]) -> list[OllamaChatMessage]:
    system = build_stage_system_prompt(STAGE, raw_text)
    listed = [{"header": p.header, "location": p.location} for p in pairs]
    user = (
        "Bulletin text:\n<<<\n" + raw_text + "\n>>>\n\n"
        "Parser pairs already extracted (do not repeat these):\n"
        + json.dumps(listed, ensure_ascii=False)
    )
    return [OllamaChatMessage(role="system", content=system), OllamaChatMessage(role="user", content=user)]


def parse_proposals(raw_response: str) -> list[dict[str, str]]:
    """Strict parse: anything that is not the documented shape raises ValueError."""
    data = json.loads(raw_response)
    if not isinstance(data, dict) or not isinstance(data.get("missing"), list):
        raise ValueError("cross-check response lacks a 'missing' list")
    proposals: list[dict[str, str]] = []
    for entry in data["missing"][:MAX_PROPOSALS]:
        if not isinstance(entry, dict):
            continue
        fields = {k: entry.get(k) for k in ("header", "location", "evidence_span")}
        if all(isinstance(v, str) and v.strip() for v in fields.values()):
            proposals.append({k: v.strip() for k, v in fields.items()})  # type: ignore[union-attr]
    return proposals


def _contains(haystack: str, needle: str) -> bool:
    return normalize_token(needle) in normalize_token(haystack)


def _is_duplicate(item: ParsedSummaryItem, existing: Sequence[ParserPair], accepted: Sequence[AcceptedAddition]) -> bool:
    villages = {item.primary_village.id} | ({item.secondary_village.id} if item.secondary_village else set())
    for pair in existing:
        if pair.condition_id == item.condition_id and villages & {pair.primary_village_id, pair.secondary_village_id}:
            return True
    for add in accepted:
        other = add.item
        if other.condition_id == item.condition_id and other.primary_village.id == item.primary_village.id:
            return True
    return False


def evaluate_proposal(
    proposal: Mapping[str, str],
    raw_text: str,
    existing: Sequence[ParserPair],
    result: CrosscheckResult,
    gazetteer: GazetteerSnapshot,
    headers: HeaderDictionarySnapshot,
    anchor_date: date | None,
) -> None:
    header, location, evidence = proposal["header"], proposal["location"], proposal["evidence_span"]
    if evidence not in raw_text:
        result.drop("evidence_not_verbatim")
        return
    if not _contains(evidence, location):
        result.drop("location_not_in_evidence")
        return
    entry, _ = headers.resolve(header)
    if entry is None or entry.status != "approved" or not entry.condition_ids:
        result.review.append(ReviewAddition("unknown_header", header, location, evidence))
        return
    # Re-run the strict parser on a one-line bulletin: same matcher, same rules.
    mini = parse_summary(f"{header}:\n- {location}", gazetteer, headers, LEXICON, anchor_date)
    if not mini.items:
        result.review.append(ReviewAddition("unresolved_location", header, location, evidence))
        return
    for item in mini.items:
        if _is_duplicate(item, existing, result.accepted):
            result.drop("duplicate_of_parser_item")
            continue
        result.accepted.append(AcceptedAddition(header, location, evidence, item))


async def crosscheck_summary(
    raw_text: str,
    parser_pairs: Sequence[ParserPair],
    *,
    gazetteer: GazetteerSnapshot,
    headers: HeaderDictionarySnapshot,
    anchor_date: date | None,
    client: OllamaChatClient | None = None,
    enabled: bool | None = None,
    known_unresolved: Sequence[str] = (),
) -> CrosscheckResult:
    """Ask the model for missed pairs; return only code-verified additions."""
    result = CrosscheckResult()
    if not (settings.summary_crosscheck_enabled if enabled is None else enabled):
        return result
    result.called = True
    try:
        chat = client or build_crosscheck_client()
        messages = build_messages(raw_text, parser_pairs)
        raw_response = await asyncio.wait_for(
            asyncio.to_thread(chat.chat, messages, response_format=RESPONSE_SCHEMA, temperature=0.0),
            timeout=settings.summary_crosscheck_timeout_seconds + 5,
        )
        proposals = parse_proposals(raw_response)
    except Exception as exc:  # timeout, connection error, invalid JSON: parser result stands
        result.error = f"crosscheck skipped: {type(exc).__name__}: {exc}"[:500]
        logger.warning("summary cross-check skipped: %s", result.error)
        return result
    already_in_review = {normalize_token(text) for text in known_unresolved}
    for proposal in proposals:
        key = normalize_token(proposal["location"])
        if key in already_in_review:
            result.drop("already_in_review")
            continue
        before = len(result.review)
        evaluate_proposal(proposal, raw_text, parser_pairs, result, gazetteer, headers, anchor_date)
        if len(result.review) > before:
            already_in_review.add(key)  # one review reason per place
    return result


def record_parser_misses(message_id: int | None, additions: Sequence[AcceptedAddition], *, path: Path = MISSES_PATH) -> None:
    """Append accepted LLM items to the review file (parser gaps to turn into grammar fixes)."""
    if not additions:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        seen: set[tuple] = set()
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                    seen.add((row.get("message_id"), row.get("header"), row.get("location"), row.get("evidence")))
                except ValueError:
                    continue
        with path.open("a", encoding="utf-8") as handle:
            for add in additions:
                key = (message_id, add.header, add.location, add.evidence_span)
                if key in seen:
                    continue
                handle.write(json.dumps(
                    {"message_id": message_id, "header": add.header, "location": add.location,
                     "evidence": add.evidence_span, "model": settings.summary_crosscheck_model,
                     "recorded_at": datetime.now(timezone.utc).isoformat()},
                    ensure_ascii=False,
                ) + "\n")
    except OSError:
        logger.warning("could not write %s", path, exc_info=True)
