"""Arabic casualty wording shared by deterministic (non-LLM) casualty checks.

knowledge: every word list comes from terminology YAML —
  casualty_gender.yaml  singular / dual / plural casualty nouns
  casualty_wording.yaml verbs, vague quantifiers, explicit-none phrases,
                        obituary markers, strike-list headings,
                        demographic nouns, spelled-out numbers
code-logic: normalization, tokenization, adjacency and matching rules below.

All matching runs on normalized text (hamza/alef unified, ة→ه, ى→ي, tashkeel
and tatweel removed) while every returned span is a verbatim slice of the
original text, so it can be used as an ``evidence_span``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from app.core.llm_knowledge.loader import load_terminology
from app.core.llm_knowledge.source_headers import header_regex, strip_source_headers

DEATHS = "deaths"
INJURIES = "injuries"

_GENDER_YAML = "terminology/casualty_gender.yaml"
_WORDING_YAML = "terminology/casualty_wording.yaml"

_DROPPED_CHARS = re.compile(r"[ً-ْٰـ\u200b-\u200f\u2060\ufeff]")
_LETTER_MAP = str.maketrans("أإآٱةى", "ااااهي")
_AR = "ء-يٱ-ۓ"
_DIGIT = "0-9٠-٩"
_DIGIT_TO_ASCII = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
# Tokens within this distance of a number may bind it to a casualty noun.
ADJACENCY_WINDOW = 3
_TOKEN_EDGE = "،,.؛:!؟?()[]{}«»\"'…-–—_*|"
_BREAK_CHARS = "؛!؟?•●▪📌\n"
_ATTACHED_PREFIXES = ("و", "ف", "ب", "ل", "ك")
# Obfuscated martyr stem used to dodge platform moderation: «4 شهـ..» → «شه».
_OBFUSCATED_DEATH_STEM = "شه"
_CENSORED_CASUALTY_WORD = re.compile(
    r"(?<![ء-ي])(?P<article>ال)?(?P<stem>شه|جر|قت)[.,،…_\-]+(?![ء-ي])"
)
_CENSORED_COMPLETIONS = {"شه": "شهيد", "جر": "جريح", "قت": "قتيل"}


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NormalizedText:
    """Normalized text plus a map from each normalized char to its source index."""

    source: str
    text: str
    offsets: tuple[int, ...]

    def source_slice(self, start: int, end: int) -> str:
        """Verbatim source text covering normalized range [start, end)."""
        if end <= start:
            return ""
        return self.source[self.offsets[start] : self.offsets[end - 1] + 1]


def normalize_with_offsets(text: str | None) -> NormalizedText:
    source = text or ""
    chars: list[str] = []
    offsets: list[int] = []
    for index, char in enumerate(source):
        if _DROPPED_CHARS.match(char):
            continue
        chars.append(char.translate(_LETTER_MAP))
        offsets.append(index)
    normalized = "".join(chars)
    # Restore moderation-censored martyr spellings before token detection:
    # «الشهـ..» / «الشهـ,,,» / «شهيـ» -> «الشهيد» / «شهيد».
    while (match := _CENSORED_CASUALTY_WORD.search(normalized)) is not None:
        replacement = f"{match.group('article') or ''}{_CENSORED_COMPLETIONS[match.group('stem')]}"
        source_offset = offsets[max(match.start(), match.end() - 1)]
        normalized = normalized[: match.start()] + replacement + normalized[match.end() :]
        offsets = (
            offsets[: match.start()]
            + [source_offset] * len(replacement)
            + offsets[match.end() :]
        )
    partial_death = re.compile(r"(?<![ء-ي])(?P<article>ال)?شهي(?![ء-ي])")
    while (match := partial_death.search(normalized)) is not None:
        replacement = f"{match.group('article') or ''}شهيد"
        source_offset = offsets[max(match.start(), match.end() - 1)]
        normalized = normalized[: match.start()] + replacement + normalized[match.end() :]
        offsets = offsets[: match.start()] + [source_offset] * len(replacement) + offsets[match.end() :]
    return NormalizedText(source=source, text=normalized, offsets=tuple(offsets))


def normalize_casualty_text(text: str | None) -> str:
    """Hamza/alef unification, ة→ه, ى→ي, tashkeel and tatweel removed."""
    return normalize_with_offsets(text).text


# ---------------------------------------------------------------------------
# Vocabulary (loaded once from YAML)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Vocabulary:
    singular: dict[str, dict[str, str]]  # kind -> {term: gender}
    dual: dict[str, dict[str, str]]
    terms: dict[str, frozenset[str]]  # kind -> every casualty term
    demographic: dict[str, str]  # term -> children | female | male
    demographic_counts: dict[str, int]  # «طفلان» -> 2
    singular_verbal_nouns: dict[str, str]  # «استشهاد» -> deaths
    singular_persons: dict[str, str]  # «مسعف»، «مواطنة» -> male | female | children
    dual_persons: frozenset[str]  # «شخصين»، «مواطنين» after a verbal noun = 2
    event_leads: frozenset[str]  # «وقوع»، «تسجيل» before a singular verbal noun
    hit_qualifiers: frozenset[str]  # «مباشرة» after «إصابة» = a direct hit
    spelled_numbers: dict[str, int]
    vague: tuple[str, ...]
    none_negators: tuple[str, ...]
    none_fillers: tuple[str, ...]
    none_nouns: dict[str, str]  # term -> deaths | injuries | both
    obituary: frozenset[str]
    strike_headings: frozenset[str]


def _entries(path: str, *categories: str):
    return [entry for entry in load_terminology(path) if entry.category in categories]


def _norm_terms(path: str, *categories: str) -> frozenset[str]:
    return frozenset(normalize_casualty_text(e.term) for e in _entries(path, *categories))


@lru_cache(maxsize=1)
def _vocab() -> _Vocabulary:
    def gendered(*pairs: tuple[str, str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for category, gender in pairs:
            for term in _norm_terms(_GENDER_YAML, category):
                out[term] = gender
        return out

    death_count_words = _entries(_GENDER_YAML, "death_count_word")
    singular_deaths = gendered(
        ("male_death_singular", "male"), ("female_death_singular", "female")
    )
    dual_deaths = gendered(("male_death_dual", "male"), ("female_death_dual", "female"))
    for entry in death_count_words:
        term = normalize_casualty_text(entry.term)
        gender = "female" if term.endswith("ه") else "male"
        if entry.normalized == "2":
            dual_deaths.setdefault(term, gender)
        else:
            singular_deaths.setdefault(term, gender)

    singular_injuries = gendered(
        ("male_injury_singular", "male"), ("female_injury_singular", "female")
    )
    dual_injuries = gendered(
        ("male_injury_dual", "male"), ("female_injury_dual", "female")
    )
    for entry in _entries(_WORDING_YAML, "injury_term"):
        if entry.normalized == "2":
            dual_injuries.setdefault(normalize_casualty_text(entry.term), "")
    for entry in _entries(_WORDING_YAML, "body_noun"):
        target = dual_deaths if entry.normalized == "2" else singular_deaths
        target.setdefault(normalize_casualty_text(entry.term), "")

    death_plurals = _norm_terms(_GENDER_YAML, "male_death_plural", "female_death_plural")
    injury_plurals = _norm_terms(
        _GENDER_YAML, "male_injury_plural", "female_injury_plural"
    )
    death_terms = _norm_terms(_WORDING_YAML, "death_term")
    injury_terms = _norm_terms(_WORDING_YAML, "injury_term")

    return _Vocabulary(
        singular={DEATHS: singular_deaths, INJURIES: singular_injuries},
        dual={DEATHS: dual_deaths, INJURIES: dual_injuries},
        terms={
            DEATHS: frozenset(singular_deaths) | frozenset(dual_deaths) | death_plurals | death_terms,
            INJURIES: frozenset(singular_injuries)
            | frozenset(dual_injuries)
            | injury_plurals
            | injury_terms,
        },
        demographic={
            normalize_casualty_text(e.term): e.meaning
            for e in _entries(_WORDING_YAML, "demographic_noun")
        },
        singular_verbal_nouns={
            normalize_casualty_text(e.term): e.meaning
            for e in _entries(_WORDING_YAML, "singular_verbal_noun")
        },
        singular_persons={
            **{
                normalize_casualty_text(e.term): e.meaning
                for e in _entries(_WORDING_YAML, "person_singular")
            },
            **{term: "male" for term in _norm_terms(_GENDER_YAML, "male_role_noun")},
            **{term: "female" for term in _norm_terms(_GENDER_YAML, "female_role_noun")},
        },
        dual_persons=_norm_terms(_WORDING_YAML, "person_dual"),
        event_leads=_norm_terms(_WORDING_YAML, "event_lead"),
        hit_qualifiers=_norm_terms(_WORDING_YAML, "hit_qualifier"),
        demographic_counts={
            normalize_casualty_text(e.term): int(e.normalized)
            for e in _entries(_WORDING_YAML, "demographic_noun")
            if e.normalized
        },
        spelled_numbers={
            normalize_casualty_text(e.term): int(e.normalized)
            for e in _entries(_WORDING_YAML, "spelled_number")
            if e.normalized
        },
        vague=tuple(sorted(_norm_terms(_WORDING_YAML, "vague_quantifier"), key=len, reverse=True)),
        none_negators=tuple(
            sorted(_norm_terms(_WORDING_YAML, "none_negator"), key=len, reverse=True)
        ),
        none_fillers=tuple(_norm_terms(_WORDING_YAML, "none_filler")),
        none_nouns={
            normalize_casualty_text(e.term): e.meaning
            for e in _entries(_WORDING_YAML, "none_noun")
        },
        obituary=_norm_terms(_WORDING_YAML, "obituary_marker"),
        strike_headings=_norm_terms(_WORDING_YAML, "strike_heading"),
    )


def _alternation(terms) -> str:
    return "|".join(re.escape(term) for term in sorted(set(terms), key=len, reverse=True))


# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------


def _page_header_re() -> re.Pattern[str] | None:
    """Registered channel/page headers (``terminology/source_headers.yaml``)."""
    return header_regex()


def _mask_page_header(text: str) -> str:
    pattern = _page_header_re()
    if pattern is None:
        return text
    return pattern.sub(lambda m: " " * len(m.group(0)), text)


def strip_page_header(text: str | None) -> str:
    """Remove registered channel/page headers (and spelling variants) from *text*."""
    return strip_source_headers(text)


_BARE_CASUALTY_TOKENS = frozenset(
    normalize_with_offsets(word).text
    for word in (
        "شهيد", "الشهيد", "شهيدة", "الشهيدة", "شهداء", "الشهداء",
        "جريح", "الجريح", "جريحة", "الجريحة", "جرحى", "الجرحى",
        "قتيل", "القتيل", "قتيلة", "القتيلة",
    )
)
_MEMORIAL_WORDS = re.compile(
    r"(?<![ء-ي])(?:رحم|رحمه|رحمة|ذكري|الذكري|روح|ارواح|تغمد|طيب|ثري|تشييع|جنازه|مضي)(?![ء-ي])"
)
_FUNCTION_WORDS = frozenset({"و", "في", "من", "على", "عن", "الى", "ال", "ب", "ل"})


def is_bare_casualty_token(span: str | None) -> bool:
    """True for a span that is only «شهيد» / «الشهيد» / «جريح» … with no number or noun."""
    folded = normalize_with_offsets(span).text.strip(" \t\n.,،:;؛-–—_*|()[]«»\"'")
    return folded in _BARE_CASUALTY_TOKENS


def bare_token_lacks_event_context(body: str | None, span: str | None) -> bool:
    """A bare martyr/injured token counts only in a sentence that says something else.

    Rejected: the token alone on its line/sentence («الشهيد»), or inside a memorial
    or obituary sentence («رحم الله الشهيد»). «الرمادية: شهيد وجريح» is a place
    label plus the token and stays valid.
    """
    if not is_bare_casualty_token(span):
        return False
    prepared = _prepared(body)
    needle = normalize_with_offsets(span).text.strip()
    if not needle:
        return True
    for match in re.finditer(re.escape(needle), prepared.text):
        start = prepared.text.rfind("\n", 0, match.start())
        for mark in ".!؟?؛":
            start = max(start, prepared.text.rfind(mark, 0, match.start()))
        ends = [i for i in (prepared.text.find(m, match.end()) for m in ".!؟?؛\n") if i != -1]
        sentence = prepared.text[start + 1 : min(ends) if ends else len(prepared.text)]
        rest = sentence.replace(needle, " ", 1)
        words = [w for w in re.findall(rf"[{_AR}]+", rest) if w not in _FUNCTION_WORDS]
        if not words or _MEMORIAL_WORDS.search(rest) or is_obituary(rest):
            continue
        return False
    return True


def _prepared(text: str | None) -> NormalizedText:
    """Normalized text with page headers blanked out (length preserved)."""
    normalized = normalize_with_offsets(text)
    return NormalizedText(
        source=normalized.source,
        text=_mask_page_header(normalized.text),
        offsets=normalized.offsets,
    )


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Token:
    raw: str
    core: str
    start: int
    end: int

    @property
    def ends_sentence(self) -> bool:
        stripped = self.raw.rstrip("\"'»)")
        if any(char in _BREAK_CHARS for char in self.raw):
            return True
        # A single final dot ends a sentence; «..» is obfuscation or ellipsis.
        return stripped.endswith(".") and not stripped.endswith("..")


def _core(raw: str) -> str:
    joined = re.sub(rf"(?<=[{_AR}])[.,…_]+(?=[{_AR}])", "", raw)
    # Drop emoji and punctuation glued to the word: «⭕شهيدان»، «🚨الشهيدة».
    return re.sub(r"^\W+|\W+$", "", joined)


def _tokens(text: str) -> list[_Token]:
    return [
        _Token(raw=m.group(0), core=_core(m.group(0)), start=m.start(), end=m.end())
        for m in re.finditer(r"\S+", text)
    ]


def _stems(core: str, *, allow_article: bool = True) -> list[str]:
    stems = [core]
    for prefix in _ATTACHED_PREFIXES:
        if core.startswith(prefix) and len(core) > 3:
            stems.append(core[1:])
    if allow_article:
        for stem in list(stems):
            for article in ("ال", "لل"):
                if stem.startswith(article) and len(stem) > 3:
                    stems.append(stem[len(article) :])
    return stems


def _has_article(core: str) -> bool:
    return any(
        stem.startswith(("ال", "لل")) for stem in _stems(core, allow_article=False)
    )


def _token_kind(token: _Token) -> str | None:
    vocab = _vocab()
    stems = _stems(token.core)
    for kind in (DEATHS, INJURIES):
        if any(stem in vocab.terms[kind] for stem in stems):
            return kind
    if any(stem == _OBFUSCATED_DEATH_STEM for stem in stems):
        return DEATHS
    return None


def _token_demographic(token: _Token) -> str | None:
    demographic = _vocab().demographic
    for stem in _stems(token.core):
        if stem in demographic:
            return demographic[stem]
    return None


def _is_url_like(raw: str) -> bool:
    return bool(re.search(r"https?|www|@|#|\.[a-z]{2,}|/[A-Za-z]", raw))


def _token_digit_value(token: _Token) -> int | None:
    """Standalone casualty-capable number; dates, times, URLs and «(n)» are not."""
    raw = token.raw
    if _is_url_like(raw):
        return None
    stripped = raw.strip("،,.؛:!؟?«»\"'")
    if re.fullmatch(rf"\([{_DIGIT}]+\)", stripped):
        return None
    stripped = re.sub(rf"^[^{_DIGIT}وف]+|[^{_DIGIT}]+$", "", stripped)
    body = stripped
    if body[:1] in ("و", "ف"):
        body = body[1:]
    if re.fullmatch(rf"[{_DIGIT}]+", body):
        return int(body.translate(_DIGIT_TO_ASCII))
    return None


def _token_spelled_value(token: _Token) -> int | None:
    numbers = _vocab().spelled_numbers
    for stem in _stems(token.core, allow_article=False):
        if stem in numbers:
            return numbers[stem]
    return None


def _is_age_number(tokens: list[_Token], index: int) -> bool:
    """True for ages such as «عمره 4 سنوات» / «4 أعوام»."""
    nearby = {
        stem
        for j in range(max(0, index - 2), min(len(tokens), index + 3))
        if j != index
        for stem in _stems(tokens[j].core)
    }
    return bool(nearby & {"عمره", "عمرها", "سنوات", "سنه", "اعوام", "عاما"})


# ---------------------------------------------------------------------------
# Strike-count lists: «الغارات من الطيران الحربي: • النبطية الفوقا (١١)»
# ---------------------------------------------------------------------------


def _strike_list_regions(text: str) -> list[tuple[int, int]]:
    headings = _vocab().strike_headings
    if not headings:
        return []
    heading_re = re.compile(
        rf"(?<![{_AR}])(?:و)?(?:{_alternation(headings)})(?![{_AR}])[^\n:]{{0,40}}:"
    )
    regions: list[tuple[int, int]] = []
    for match in heading_re.finditer(text):
        # Headings are often followed by a blank line; the list starts after it.
        rest = text[match.end() :]
        body_start = match.end() + len(rest) - len(rest.lstrip())
        blank = re.search(r"\n\s*\n", text[body_start:])
        end = body_start + blank.start() if blank else len(text)
        regions.append((match.start(), end))
    return regions


def strike_list_number_spans(text: str | None) -> list[str]:
    """Verbatim «place (n)» entries listed under a strike/raid heading."""
    prepared = _prepared(text)
    spans: list[str] = []
    for start, end in _strike_list_regions(prepared.text):
        for match in re.finditer(rf"[^\n•●▪]*?\(\s*[{_DIGIT}]+\s*\)", prepared.text[start:end]):
            spans.append(
                prepared.source_slice(start + match.start(), start + match.end()).strip()
            )
    return spans


def _in_regions(index: int, regions: list[tuple[int, int]]) -> bool:
    return any(start <= index < end for start, end in regions)


# ---------------------------------------------------------------------------
# Count mentions (numbers and count words bound to a casualty noun)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CountMention:
    kind: str | None  # deaths | injuries | None (demographic-only)
    value: int
    rule: str  # digit | spelled_number | singular | dual
    text: str  # verbatim source slice
    gender_or_group: str | None = None  # male | female | children
    # False when a demographic noun is closer than the casualty noun:
    # «33 جريحا من بينهم 6 أطفال» — 6 is a sub-count, not the injury total.
    counts_total: bool = True
    start: int = -1
    end: int = -1
    # Position of the token that supplies the numeric value.  Evidence spans
    # may begin at the casualty noun (for example, ``جرحى بينهم 4 أطفال``),
    # so claim-unit ownership must not use ``start`` for ordering.
    anchor_start: int = -1
    anchor_end: int = -1


def _neighbours(tokens: list[_Token], index: int, direction: int):
    """Yield (distance, token) up to the adjacency window, stopping at sentence ends."""
    for distance in range(1, ADJACENCY_WINDOW + 1):
        j = index + direction * distance
        if j < 0 or j >= len(tokens):
            return
        boundary = tokens[j - 1] if direction > 0 else tokens[j]
        if boundary.ends_sentence:
            return
        yield distance, j


def _bind_number(
    tokens: list[_Token], index: int
) -> tuple[str | None, int | None, str | None, bool]:
    """Nearest casualty noun (ties prefer the following token) plus a demographic noun.

    The last item is False when the demographic noun is nearer than the casualty noun.
    """
    candidates: list[tuple[int, int, int]] = []
    demographic: str | None = None
    demographic_distance = ADJACENCY_WINDOW + 1
    for direction, tie in ((1, 0), (-1, 1)):
        for distance, j in _neighbours(tokens, index, direction):
            if _token_kind(tokens[j]) is not None:
                candidates.append((distance, tie, j))
            if demographic is None and distance <= 2:
                demographic = _token_demographic(tokens[j])
                if demographic is not None:
                    demographic_distance = distance
    if not candidates:
        return None, None, demographic, demographic is None
    distance, _, j = min(candidates)
    return _token_kind(tokens[j]), j, demographic, demographic_distance >= distance


def _count_word(token: _Token) -> tuple[str, int, str, str] | None:
    """(kind, value, rule, gender) for a bare singular/dual casualty noun."""
    if _has_article(token.core):
        return None
    vocab = _vocab()
    stems = _stems(token.core, allow_article=False)
    for kind in (DEATHS, INJURIES):
        for stem in stems:
            if stem in vocab.dual[kind]:
                return kind, 2, "dual", vocab.dual[kind][stem]
            if stem in vocab.singular[kind]:
                return kind, 1, "singular", vocab.singular[kind][stem]
    return None


def _demographic_count(token: _Token) -> tuple[str, int] | None:
    """(group, value) for a counted demographic noun such as «طفلان»."""
    vocab = _vocab()
    for stem in _stems(token.core, allow_article=False):
        if stem in vocab.demographic_counts:
            return vocab.demographic[stem], vocab.demographic_counts[stem]
    return None


def _find_count_mentions(prepared: NormalizedText) -> list[CountMention]:
    tokens = _tokens(prepared.text)
    regions = _strike_list_regions(prepared.text)
    mentions: list[CountMention] = []
    consumed_number_tokens: set[int] = set()
    for index, token in enumerate(tokens):
        if index in consumed_number_tokens:
            continue
        digit = _token_digit_value(token)
        spelled = None if digit is not None else _token_spelled_value(token)
        compound_end = index
        if (
            spelled in range(3, 10)
            and index + 1 < len(tokens)
            and _token_spelled_value(tokens[index + 1]) == 10
        ):
            spelled += 10
            compound_end = index + 1
            consumed_number_tokens.add(index + 1)
        if digit is not None or spelled is not None:
            if _is_age_number(tokens, index):
                continue
            kind, j, group, counts_total = _bind_number(tokens, compound_end)
            if kind is None and group is None:
                continue
            if spelled is not None and (j is None or abs(j - compound_end) != 1):
                # Spelled numbers only count right next to a casualty noun:
                # «ثلاثة شهداء»، «إصابة اثنين».
                continue
            if _in_regions(token.start, regions) and (j is None or abs(j - index) > 1):
                continue
            value = digit if digit is not None else spelled
            if group is None and j is not None and value in (1, 2):
                # Grammatical gender in a casualty noun is never demographic
                # evidence.  Only an explicit noun such as طفل/سيدة/رجل may
                # populate a demographic field.
                group = None
            first = min(index, j) if j is not None else index
            last = max(index, j) if j is not None else index
            start = tokens[first].start
            if first == index and token.raw[:1] in ("و", "ف"):
                start += 1  # «و10 جرحى» → «10 جرحى»
            mentions.append(
                CountMention(
                    kind=kind,
                    value=value,
                    rule="digit" if digit is not None else "spelled_number",
                    text=prepared.source_slice(start, tokens[last].end).strip(_TOKEN_EDGE),
                    gender_or_group=group,
                    counts_total=counts_total,
                    start=start,
                    end=tokens[last].end,
                    anchor_start=token.start,
                    anchor_end=tokens[compound_end].end,
                )
            )
            continue
        group_count = _demographic_count(token)
        if group_count is not None:
            group, value = group_count
            mentions.append(
                CountMention(
                    kind=None,
                    value=value,
                    rule="dual",
                    text=prepared.source_slice(token.start, token.end).strip(_TOKEN_EDGE),
                    gender_or_group=group,
                    start=token.start,
                    end=token.end,
                    anchor_start=token.start,
                    anchor_end=token.end,
                )
            )
            continue
        previous = tokens[index - 1] if index > 0 else None
        if previous is not None and not previous.ends_sentence and (
            _token_digit_value(previous) is not None
            or _token_spelled_value(previous) is not None
            or previous.core in {"بين", "احد", "كل"}
        ):
            # «10 اصابات بين شهيد وجريح» / «3 شهيد» are not singular counts.
            continue
        word = _count_word(token)
        if word is not None:
            kind, value, rule, gender = word
            mentions.append(
                CountMention(
                    kind=kind,
                    value=value,
                    rule=rule,
                    text=prepared.source_slice(token.start, token.end).strip(_TOKEN_EDGE),
                    gender_or_group=None,
                    start=token.start,
                    end=token.end,
                    anchor_start=token.start,
                    anchor_end=token.end,
                )
            )
            continue
        verbal = _singular_verbal_count(tokens, index)
        if verbal is not None:
            kind, group, first, last, value = verbal
            mentions.append(
                CountMention(
                    kind=kind,
                    value=value,
                    rule="singular" if value == 1 else "dual",
                    text=prepared.source_slice(tokens[first].start, tokens[last].end).strip(
                        _TOKEN_EDGE
                    ),
                    gender_or_group=group,
                    start=tokens[first].start,
                    end=tokens[last].end,
                    anchor_start=token.start,
                    anchor_end=token.end,
                )
            )
            continue
        named = _named_victim_gender(tokens, index)
        if named is not None:
            mentions.append(
                CountMention(
                    kind=DEATHS,
                    value=1,
                    rule="named_singular",
                    text=prepared.source_slice(token.start, token.end).strip(_TOKEN_EDGE),
                    gender_or_group=named or None,
                    start=token.start,
                    end=token.end,
                    anchor_start=token.start,
                    anchor_end=token.end,
                )
            )
    return mentions


def _singular_verbal_count(
    tokens: list[_Token], index: int
) -> tuple[str, str | None, int, int, int] | None:
    """(kind, group, first, last, value) for a verbal-noun count of 1 (or 2 for a dual person).

    «استشهاد مسعف»، «إصابة مواطن»: verbal noun + indefinite singular person.
    «وقوع إصابة»، «تسجيل إصابة»: event verb + singular verbal noun, unless it is
    «إصابة مباشرة» (a direct hit on a target).
    """
    vocab = _vocab()
    kind = next(
        (
            vocab.singular_verbal_nouns[stem]
            for stem in _stems(tokens[index].core, allow_article=False)
            if stem in vocab.singular_verbal_nouns
        ),
        None,
    )
    if kind is None:
        return None
    following = (
        tokens[index + 1]
        if index + 1 < len(tokens) and not tokens[index].ends_sentence
        else None
    )
    if following is not None and not _has_article(following.core):
        for stem in _stems(following.core, allow_article=False):
            if stem in vocab.dual_persons:
                # «إصابة شخصين»: a dual person is an explicit count of 2.
                return kind, None, index, index + 1, 2
            if stem in vocab.singular_persons:
                # مواطن/مسعف/عنصر/person names establish a singular casualty,
                # not adult gender. Explicit demographic nouns are handled by
                # the demographic vocabulary only.
                return kind, vocab.demographic.get(stem), index, index + 1, 1
    previous = tokens[index - 1] if index > 0 else None
    if (
        previous is not None
        and not previous.ends_sentence
        and any(stem in vocab.event_leads for stem in _stems(previous.core))
        and (
            following is None
            or (
                _token_digit_value(following) is None
                and _token_spelled_value(following) is None
                and not any(
                    stem in vocab.hit_qualifiers
                    for stem in _stems(following.core, allow_article=False)
                )
            )
        )
    ):
        return kind, None, index - 1, index, 1
    return None


def _named_victim_gender(tokens: list[_Token], index: int) -> str | None:
    """«الشهيدة إسراء بهجة… إرتقت في غارة»: one named victim with a death verb.

    Only a definite singular martyr noun with a death verb in the same sentence
    counts; «منزل الشهيد علي معلم» (no death verb) does not. Obfuscated forms
    («الشهـ..»، «الشهيـ دة») match with unknown gender ("").
    """
    token = tokens[index]
    if not _has_article(token.core):
        return None
    singular = _vocab().singular[DEATHS]
    stems = _stems(token.core)
    gender = next((singular[stem] for stem in stems if stem in singular), None)
    if gender is None and any(
        stem.startswith(_OBFUSCATED_DEATH_STEM) and len(stem) <= 3 for stem in stems[1:]
    ):
        gender = ""
    if gender is None:
        return None
    start = index
    while start > 0 and not tokens[start - 1].ends_sentence:
        start -= 1
    end = index
    while end < len(tokens) - 1 and not tokens[end].ends_sentence:
        end += 1
    death_terms = _vocab().terms[DEATHS]
    for j in range(start, end + 1):
        if j == index or _count_word(tokens[j]) is not None:
            continue
        if any(stem in death_terms for stem in _stems(tokens[j].core)) and not _has_article(
            tokens[j].core
        ):
            return gender
    return None


def find_count_mentions(text: str | None) -> tuple[CountMention, ...]:
    """Every explicit casualty count in *text* (page header ignored)."""
    return tuple(_find_count_mentions(_prepared(text)))


def has_casualty_wording(text: str | None, kind: str) -> bool:
    """Whether *text* mentions casualty wording of *kind*, even without a count."""
    if kind not in (DEATHS, INJURIES):
        raise ValueError(f"unsupported casualty kind: {kind}")
    terms = _vocab().terms[kind] | frozenset(
        term for term, term_kind in _vocab().singular_verbal_nouns.items()
        if term_kind == kind
    )
    if not terms:
        return False
    return bool(
        re.search(
            rf"(?<![{_AR}])(?:و|ف|ب|ل|ك)?(?:ال|لل)?"
            rf"(?:{_alternation(terms)})(?![{_AR}])",
            _prepared(text).text,
        )
    )


def find_count_words(text: str | None) -> tuple[CountMention, ...]:
    """Singular/dual nouns and spelled-out numbers only (no digits)."""
    return tuple(
        m
        for m in find_count_mentions(text)
        if m.rule in ("singular", "dual", "spelled_number") and m.kind
    )


def field_kind(field_name: str) -> tuple[str, str | None]:
    """('deaths'|'injuries', demographic group or None) for an ExtractionCasualties field."""
    base = field_name.removeprefix("total_")
    kind = DEATHS if base.endswith("deaths") else INJURIES
    for group in ("male", "female", "children"):
        if base.startswith(f"{group}_"):
            return kind, group
    return kind, None


def find_supporting_mention(
    text: str | None,
    field_name: str,
    value: int,
) -> CountMention | None:
    """First mention in *text* that explicitly states *value* for *field_name*."""
    kind, group = field_kind(field_name)
    for mention in find_count_mentions(text):
        if mention.value != value:
            continue
        if group is None:
            if mention.kind == kind and mention.counts_total:
                return mention
            continue
        if mention.gender_or_group == group and mention.kind in (None, kind):
            return mention
    return None


# ---------------------------------------------------------------------------
# Explicit none, vague quantifiers, obituaries
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _none_re() -> re.Pattern[str]:
    vocab = _vocab()
    return re.compile(
        rf"(?<![{_AR}])(?:و)?(?:{_alternation(vocab.none_negators)})"
        rf"(?:\s+(?:{_alternation(vocab.none_fillers)}))*"
        rf"\s+(?:ال)?(?P<noun>{_alternation(vocab.none_nouns)})(?![{_AR}])"
    )


def find_explicit_none(text: str | None, kind: str) -> str | None:
    """Verbatim «دون تسجيل إصابات»-style phrase covering *kind*, if any."""
    prepared = _prepared(text)
    nouns = _vocab().none_nouns
    for match in _none_re().finditer(prepared.text):
        if nouns.get(match.group("noun")) in (kind, "both"):
            return prepared.source_slice(match.start(), match.end()).strip()
    return None


def has_explicit_none(text: str | None, kind: str) -> bool:
    return find_explicit_none(text, kind) is not None


def has_vague_quantifier(text: str | None, kind: str | None = None) -> bool:
    """True for «عشرات الجرحى»، «وقوع إصابات»، «عدد من الشهداء» (optionally per kind)."""
    prepared = _prepared(text)
    vague_re = re.compile(
        rf"(?<![{_AR}])(?:و|ب)?(?:{_alternation(_vocab().vague)})(?![{_AR}])"
    )
    for match in vague_re.finditer(prepared.text):
        following = _tokens(prepared.text[match.end() :])[:2]
        for token in following:
            token_kind = _token_kind(token)
            if token_kind is not None and _count_word(token) is None and (
                kind is None or token_kind == kind
            ):
                return True
    return False


def is_obituary(text: str | None) -> bool:
    """«تنعى»، «ينعى»، «تزف»: mourning a named victim, not a new casualty event."""
    obituary = _vocab().obituary
    if not obituary:
        return False
    return bool(
        re.search(
            rf"(?<![{_AR}])(?:و)?(?:{_alternation(obituary)})(?![{_AR}])",
            _prepared(text).text,
        )
    )


def mentions_named_victim(text: str | None) -> bool:
    """«الشهيد فلان»: a definite singular/dual martyr noun refers to a known person."""
    vocab = _vocab()
    words = list(vocab.singular[DEATHS]) + list(vocab.dual[DEATHS])
    return bool(
        re.search(
            rf"(?<![{_AR}])(?:و|ل)?(?:ال|لل)(?:{_alternation(words)})(?![{_AR}])",
            _prepared(text).text,
        )
    )


# ---------------------------------------------------------------------------
# Sentences
# ---------------------------------------------------------------------------


def sentences(text: str | None) -> list[str]:
    """Split on sentence punctuation, bullets and newlines (not on «،»)."""
    parts = re.split(r"[\n؛!؟?•●▪📌|]+|(?<!\.)\.(?!\.)(?=\s|$)", text or "")
    return [part.strip() for part in parts if part and part.strip()]
