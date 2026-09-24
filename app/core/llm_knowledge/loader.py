from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

import yaml

from app.core.text_normalization import normalize_arabic_text

logger = logging.getLogger(__name__)

KNOWLEDGE_ROOT = Path(__file__).resolve().parent

# Dash-route and multi-clause signals for situational rule loading.
_DASH_ROUTE_RE = re.compile(
    r"طريق(?:\s+عام)?\s+"
    r"[\u0600-\u06ff][\u0600-\u06ff\s]{1,60}?\s*[-–—]\s*"
    r"[\u0600-\u06ff][\u0600-\u06ff\s]{1,60}?"
)
_BETWEEN_ROUTE_RE = re.compile(
    r"طريق(?:\s+عام)?\s+بين\s+"
    r"[\u0600-\u06ff][\u0600-\u06ff\s]{1,60}?\s+و\s*"
    r"[\u0600-\u06ff][\u0600-\u06ff\s]{1,60}?"
)
_MULTI_VILLAGE_SEPARATORS = ("؛", ";", ":\n", " : ")
_FUZZY_AREA_RE = re.compile(
    r"(?:في\s+)?(?:محيط|قرب|بالقرب\s+من|بين)\s+"
    r"[\u0600-\u06ff][\u0600-\u06ff\s]{1,100}?\s+و\s*"
    r"[\u0600-\u06ff]"
)

SituationalTrigger = Callable[[str], bool]


def is_multi_village_candidate(text: str) -> bool:
    """True when bulletin text likely names multiple target locations."""
    normalized = normalize_arabic_text(text or "")
    if not normalized:
        return False
    # Connector-led second events: «كما غارة أخرى في بلدة Y»
    # After normalize_arabic_text, ة → ه so match بلده as well as بلدة.
    if re.search(
        r"(?:كما|ايضا|بالاضافه|وفي\s+سياق\s+متصل).{0,60}بلد[ةه]\s+[\u0600-\u06ff]{2,}",
        normalized,
    ):
        return True
    # Shared bulletin list: «بلدات A، B، C»
    if re.search(
        r"بلدات\s+[\u0600-\u06ff].{0,80}[،,]",
        normalized,
    ):
        return True
    fuzzy_match = _FUZZY_AREA_RE.search(normalized)
    if fuzzy_match and not (
        normalized[max(0, fuzzy_match.start() - 12) : fuzzy_match.start()].find(
            "طريق"
        ) >= 0
        and normalized[fuzzy_match.start() :].startswith("بين")
    ):
        return False
    if _DASH_ROUTE_RE.search(normalized) or _BETWEEN_ROUTE_RE.search(normalized):
        return True
    if sum(normalized.count(sep) for sep in _MULTI_VILLAGE_SEPARATORS) >= 1:
        # Colon/semicolon lists like «المنصوري: …؛ مجدل زون: …»
        if re.search(r"[\u0600-\u06ff]{2,}\s*:\s*[\u0600-\u06ff]", normalized):
            return True
    # «X و Y» between two plausible place tokens with targeting verb
    if re.search(
        r"(?:استهدف|قصف|غارة).{0,80}(?:و|،)\s*[\u0600-\u06ff]{2,}",
        normalized,
    ):
        return True
    return False


# Injured → deceased / toll-update wording. Deliberately broader than the
# deterministic backstop so the transition rules are loaded whenever a post
# could carry a transition; missing them is worse than the extra tokens.
_CASUALTY_TRANSITION_RE = re.compile(
    r"متاثر|فارق\s+الحياه|احد\s+(?:جريحي|الجرحى|المصابين)"
    r"|(?:لتصبح|لترتفع|ارتفع|ارتفاع)\s+(?:عدد\s+)?(?:الحصيله|الشهداء|الضحايا|القتلى)"
    r"|تحديث\s+الحصيله|بقي\s+\S+\s+(?:جرحى|جريح|مصاب)"
)


def has_casualty_transition_language(text: str) -> bool:
    """True when the post may describe injured→deceased or a toll update."""
    normalized = normalize_arabic_text(text or "")
    if not normalized:
        return False
    if _CASUALTY_TRANSITION_RE.search(normalized):
        return True
    # Imported lazily: the backstop module itself imports this loader.
    from app.news.services.incident_details.casualty_transition_backstop import (
        detect_casualty_transition_backstop,
    )

    return detect_casualty_transition_backstop(text).plausible


_TRIGGER_REGISTRY: dict[str, SituationalTrigger] = {
    "is_multi_village_candidate": is_multi_village_candidate,
    "has_casualty_transition_language": has_casualty_transition_language,
}


@dataclass(frozen=True)
class TerminologyEntry:
    term: str
    category: str
    meaning: str
    notes: str | None = None
    normalized: str | None = None


@dataclass
class PromptContext:
    """Assembled knowledge fragment for prompt construction."""

    stage: str
    message_text: str
    terminology: list[TerminologyEntry] = field(default_factory=list)
    rules: str = ""
    fewshot_examples: list[dict[str, Any]] = field(default_factory=list)
    situational_rules_loaded: list[str] = field(default_factory=list)

    def as_prompt_fragment(self) -> str:
        """Concatenate rules, matched terminology, and few-shot block."""
        parts: list[str] = []
        if self.rules.strip():
            parts.append(self.rules.strip())
        if self.terminology:
            lines = ["## Matched terminology (from source text)"]
            for entry in self.terminology:
                line = f"- {entry.term} → {entry.meaning} ({entry.category})"
                if entry.notes:
                    line += f"; {entry.notes}"
                lines.append(line)
            parts.append("\n".join(lines))
        if self.fewshot_examples:
            lines = ["## Examples"]
            for index, example in enumerate(self.fewshot_examples, start=1):
                lines.append(f"Example {index} input: {example.get('input', '')}")
                expected = example.get("expected")
                if expected is not None:
                    lines.append(f"Expected: {json.dumps(expected, ensure_ascii=False)}")
                note = example.get("note")
                if note:
                    lines.append(f"Note: {note}")
            parts.append("\n".join(lines))
        return "\n\n".join(parts)


@lru_cache(maxsize=1)
def _load_index(index_path: str) -> dict[str, Any]:
    path = Path(index_path)
    if not path.is_file():
        logger.warning("llm_knowledge index missing: %s", path)
        return {}
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


@lru_cache(maxsize=32)
def _load_terminology_file(relative_path: str, root: str) -> tuple[TerminologyEntry, ...]:
    path = Path(root) / relative_path
    if not path.is_file():
        logger.warning("llm_knowledge terminology file missing: %s", path)
        return ()
    with path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or []
    entries: list[TerminologyEntry] = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("term"):
            continue
        entries.append(
            TerminologyEntry(
                term=str(item["term"]),
                category=str(item.get("category", "")),
                meaning=str(item.get("meaning", "")),
                notes=item.get("notes"),
                normalized=item.get("normalized"),
            )
        )
    return tuple(entries)


@lru_cache(maxsize=16)
def _load_rule_file(relative_path: str, root: str) -> str:
    path = Path(root) / relative_path
    if not path.is_file():
        logger.warning("llm_knowledge rule file missing: %s", path)
        return ""
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=8)
def _load_fewshot_file(relative_path: str, root: str) -> tuple[dict[str, Any], ...]:
    path = Path(root) / relative_path
    if not path.is_file():
        logger.warning("llm_knowledge fewshot file missing: %s", path)
        return ()
    examples: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Invalid JSONL line in %s: %s", path, line[:80])
                continue
            if isinstance(payload, dict):
                examples.append(payload)
    return tuple(examples)


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    return dot  # embeddings are normalized in EmbeddingService


def scan_terminology(
    text: str,
    entries: tuple[TerminologyEntry, ...],
) -> list[TerminologyEntry]:
    normalized = normalize_arabic_text(text or "")
    if not normalized:
        return []
    matched: list[TerminologyEntry] = []
    seen: set[str] = set()
    for entry in entries:
        probe = normalize_arabic_text(entry.normalized or entry.term)
        if probe and probe in normalized and probe not in seen:
            matched.append(entry)
            seen.add(probe)
    return matched


class PromptBuilder:
    """Load and assemble stage-specific LLM knowledge fragments."""

    def __init__(
        self,
        root: Path | None = None,
        *,
        embedding_service: Any | None = None,
    ) -> None:
        self.root = root or KNOWLEDGE_ROOT
        self._embedding_service = embedding_service
        self._index_path = str(self.root / "index.yaml")

    def clear_cache(self) -> None:
        _load_index.cache_clear()
        _load_terminology_file.cache_clear()
        _load_rule_file.cache_clear()
        _load_fewshot_file.cache_clear()

    def build(self, stage: str, message_text: str) -> PromptContext:
        index = _load_index(self._index_path)
        stage_config = index.get(stage)
        if not stage_config:
            logger.warning("Unknown llm_knowledge stage: %s", stage)
            return PromptContext(stage=stage, message_text=message_text)

        root_str = str(self.root)
        terminology_entries: list[TerminologyEntry] = []
        for relative in stage_config.get("terminology") or []:
            terminology_entries.extend(
                _load_terminology_file(relative, root_str)
            )
        matched = scan_terminology(message_text, tuple(terminology_entries))

        rules_parts: list[str] = []
        situational_loaded: list[str] = []
        rules_config = stage_config.get("rules") or {}
        for relative in rules_config.get("core") or []:
            content = _load_rule_file(relative, root_str)
            if content:
                rules_parts.append(content)

        for situational in rules_config.get("situational") or []:
            trigger_name = situational.get("trigger", "")
            trigger_fn = _TRIGGER_REGISTRY.get(trigger_name)
            if trigger_fn is None:
                logger.warning("Unknown situational trigger: %s", trigger_name)
                continue
            if trigger_fn(message_text):
                relative = situational.get("load")
                if relative:
                    content = _load_rule_file(relative, root_str)
                    if content:
                        rules_parts.append(content)
                        situational_loaded.append(relative)

        fewshot_examples: list[dict[str, Any]] = []
        fewshot_config = stage_config.get("fewshot")
        if fewshot_config:
            source = fewshot_config.get("source")
            k = int(fewshot_config.get("k") or 3)
            if source:
                pool = list(_load_fewshot_file(source, root_str))
                fewshot_examples = self._retrieve_fewshot(
                    message_text,
                    pool,
                    k=k,
                )

        return PromptContext(
            stage=stage,
            message_text=message_text,
            terminology=matched,
            rules="\n\n".join(rules_parts),
            fewshot_examples=fewshot_examples,
            situational_rules_loaded=situational_loaded,
        )

    def _retrieve_fewshot(
        self,
        message_text: str,
        pool: list[dict[str, Any]],
        *,
        k: int,
    ) -> list[dict[str, Any]]:
        if not pool:
            return []
        if self._embedding_service is None or k <= 0:
            return pool[:k]

        try:
            query_vector = self._embedding_service.generate(message_text)
        except Exception:
            logger.exception("Few-shot embedding failed; falling back to file order")
            return pool[:k]

        scored: list[tuple[float, dict[str, Any]]] = []
        for example in pool:
            example_input = str(example.get("input") or "")
            if not example_input:
                continue
            try:
                vector = self._embedding_service.generate(example_input)
                score = _cosine_similarity(query_vector, vector)
            except Exception:
                score = 0.0
            scored.append((score, example))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [example for _, example in scored[:k]]


def get_prompt_builder(
    embedding_service: Any | None = None,
) -> PromptBuilder:
    """Factory for a cached-index PromptBuilder instance."""
    return PromptBuilder(embedding_service=embedding_service)


def load_terminology(
    relative_path: str,
    *,
    root: Path | None = None,
) -> tuple[TerminologyEntry, ...]:
    """Load a terminology YAML file (cached). Used by code-level backstops."""
    return _load_terminology_file(relative_path, str(root or KNOWLEDGE_ROOT))


def terms_by_category(
    relative_path: str,
    category: str,
    *,
    root: Path | None = None,
) -> tuple[str, ...]:
    """Return term strings for one category from a terminology file."""
    return tuple(
        entry.term
        for entry in load_terminology(relative_path, root=root)
        if entry.category == category
    )


def terms_by_meaning(
    relative_path: str,
    meaning: str,
    *,
    root: Path | None = None,
) -> tuple[str, ...]:
    """Return term strings for one meaning from a terminology file."""
    return tuple(
        entry.term
        for entry in load_terminology(relative_path, root=root)
        if entry.meaning == meaning
    )
