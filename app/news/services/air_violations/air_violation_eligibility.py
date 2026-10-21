from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from app.core.text_normalization import normalize_arabic_text
from app.news.services.air_violations.caza_alias_resolver import resolve_caza_alias


class AirViolationOutcome(str, Enum):
    """What a caller must do with a piece of text.

    ``eligible`` is the only outcome that creates an air violation.
    ``belongs_in_incidents`` is the only one that may enter the incident
    pipeline. ``reject_no_incident`` and ``hold_for_review`` must never be
    re-queued as ``parsed``: the first is a decided non-event, the second
    needs a human.
    """

    eligible = "eligible"
    belongs_in_incidents = "belongs_in_incidents"
    reject_no_incident = "reject_no_incident"
    hold_for_review = "hold_for_review"


#: The one exclusion that means "a real event happened, it just is not an air
#: violation". Only these rows belong in the incident pipeline; every other
#: exclusion is a notice, a tag or an unreadable row, and goes to a human.
KINETIC_EXCLUSION_REASON = "excluded_kinetic_casualty_or_damage"

#: Rule A -- the aircraft is attributed to someone other than Israel.
NON_ISRAELI_REASON = "rejected_non_israeli_aircraft"
#: Rule B -- the text denies or clarifies that the air activity happened.
DENIAL_REASON = "rejected_denial_or_clarification"
#: Rule B, ambiguous half -- a denial that also reports a real overflight.
DENIAL_WITH_OVERFLIGHT_REASON = "excluded_denial_with_separate_overflight"
#: Rule D -- the only location given is a country-level direction.
GENERIC_DIRECTION_REASON = "no_location_generic_direction"
#: Rule E -- a place name is present but resolved to no village.
UNMATCHED_LOCATION_REASON = "unmatched_location"
# The model labelled a report as a helicopter although the text names none.
HELICOPTER_LABEL_WITHOUT_KEYWORD_REASON = "helicopter label without helicopter keyword"

_REASON_OUTCOMES: dict[str, AirViolationOutcome] = {
    "presence_only": AirViolationOutcome.eligible,
    KINETIC_EXCLUSION_REASON: AirViolationOutcome.belongs_in_incidents,
    NON_ISRAELI_REASON: AirViolationOutcome.reject_no_incident,
    DENIAL_REASON: AirViolationOutcome.reject_no_incident,
    GENERIC_DIRECTION_REASON: AirViolationOutcome.reject_no_incident,
    UNMATCHED_LOCATION_REASON: AirViolationOutcome.hold_for_review,
    HELICOPTER_LABEL_WITHOUT_KEYWORD_REASON: AirViolationOutcome.reject_no_incident,
}


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    reason: str
    matched_terms: list[str]
    #: The place name that resolved to no village (rule E only).
    unmatched_location: str | None = field(default=None)

    @property
    def outcome(self) -> AirViolationOutcome:
        """The single switch every caller branches on."""
        if self.eligible:
            return AirViolationOutcome.eligible
        # Anything not explicitly mapped is an ambiguous row -- a channel
        # notice, a bare tag, unreadable text -- and goes to a human.
        return _REASON_OUTCOMES.get(self.reason, AirViolationOutcome.hold_for_review)

    @property
    def belongs_in_incidents(self) -> bool:
        """True when rejecting this text means it is an incident report."""
        return self.outcome is AirViolationOutcome.belongs_in_incidents

    @property
    def rejected_without_incident(self) -> bool:
        """True when the row is a decided non-event: no air violation, no incident."""
        return self.outcome is AirViolationOutcome.reject_no_incident

    @property
    def held_for_review(self) -> bool:
        return self.outcome is AirViolationOutcome.hold_for_review


_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_HASHTAG_RE = re.compile(r"#[^\s#]+")
_HANDLE_RE = re.compile(r"(?<!\w)@[\w.]+")
_LEADING_SOURCE_RE = re.compile(
    r"^\s*(?:(?:عاجل|حصري)\s*[|:\-–—]*\s*)?"
    r"(?:(?:صفحه|صفحة)\s+)?(?:الاعلامي|الإعلامي|مراسل(?:نا|\s+[^:|]+)?)"
    r"\s+(?:الشهيد\s+)?[^:\n|]{2,80}\s*[:|\-–—]\s*",
    re.IGNORECASE,
)
_TITLE_LINE_RE = re.compile(
    r"^\s*(?:(?:صفحه|صفحة)\s+)?(?:الاعلامي|الإعلامي)\s+الشهيد\s+[^:\n]{2,80}\s*$",
    re.IGNORECASE,
)
_HONORIFIC_PREFIX_RE = re.compile(
    r"^\s*(?:الشهيد\s+(?:القائد|الاعلامي|الإعلامي)|الشهيد)\s+[^:\n]{2,80}\s*[:\-–—]\s*",
    re.IGNORECASE,
)

_AIRCRAFT_TERMS = (
    "طائره", "طائرات", "طيران", "مروحيه", "مروحيات", "مسيره", "مسيرات",
    "درون", "مقاتلات", "مقاتله", "هليكوبتر",
    "helicopter", "helicopters", "aircraft", "drone", "drones", "plane",
    "planes", "jet", "jets",
)
_STATUS_UPDATE_TERMS = (
    "اخر تحديث للمناطق المتاثره",
    "عدد الدوائر الحمراء يدل علي عدد المناطق المتاثره",
)
# End-of-day digests and channel housekeeping posts list kinetic words without
# reporting an event ("...a drone, or a warplane, or an airstrike..."), so they
# must be recognised before the kinetic terms are matched. Mirrors the
# collector's NON_EVENT_NOTICE_PARTS / NON_AIR_DRONE_WORD_PATTERNS.
_NON_EVENT_NOTICE_TERMS = (
    "احصاءات نهايه اليوم",
    "احصاء التنبيهات",
    "اجمالي التنبيهات",
    "اكثر القري رصدا",
    "اكثر الاقضيه نشاطا",
    "جزء من هذه المسيره",
    "بدانا بمجموعه",
    "نرجو منكم ابلاغنا فورا",
    "عبر البوت الجديد",
)

_STRIKE_TERMS = (
    "غاره", "غارات", "غارت", "اغار", "استهدف", "استهداف", "استهدفت", "قصف", "قصفت",
    "اغتيال", "اطلاق صاروخ", "صاروخ", "قنبله", "قنابل", "انفجار",
    "تفجير", "قذيفه", "قذائف", "مدفعيه", "airstrike", "air strike", "attacked", "strike",
)
_CASUALTY_TERMS = (
    "شهيد", "شهداء", "استشهاد", "استشهد", "جريح", "جرحي", "اصابه",
    "اصابات", "قتل", "قتيل", "قتلي", "نجاه", "ناج", "ضحايا",
)
_DAMAGE_TERMS = ("تدمير", "دمار", "اضرار", "تضرر", "احتراق")
_FIRE_TERMS = ("حريق",)
_APACHE_TERMS = ("اباتشي", "apache", "ah-64")
# Terms are matched as substrings so Arabic inflections (غارة/غارات/غارتان)
# all count, which also makes place names that merely contain one of them look
# kinetic. "نهر المغارة" is a river, not a غارة.
_KINETIC_LOOKALIKE_RE = re.compile(r"(?<![^\W\d_])(?:ال)?مغار(?:ه|ات)(?![^\W\d_])")


# --------------------------------------------------------------------------
# Whole-token matching
#
# The kinetic lists above are matched as substrings on purpose, so Arabic
# inflections all count; that is also what made "نهر المغارة" look like a
# غارة, and why it needs its own lookalike guard. Every rule added below
# matches whole tokens instead, tolerating only the clitics Arabic actually
# attaches in front of a noun (the definite article and the و/ف/ب/ك/ل
# prepositions), so "اليونيفل" and "لليونيفيل" hit while "المغارة" cannot
# reach "غارة".
# --------------------------------------------------------------------------
_ARABIC_LETTER = r"[^\W\d_]"
_CLITIC_PREFIX = r"(?:[وفبكل]{0,2}(?:ال)?)"


def _token_pattern(term: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?<!{_ARABIC_LETTER}){_CLITIC_PREFIX}{re.escape(term)}(?!{_ARABIC_LETTER})"
    )


def _compile_tokens(terms: tuple[str, ...]) -> tuple[tuple[str, re.Pattern[str]], ...]:
    return tuple((term, _token_pattern(term)) for term in terms)


def _matched_tokens(
    text: str, compiled: tuple[tuple[str, re.Pattern[str]], ...]
) -> list[str]:
    return [term for term, pattern in compiled if pattern.search(text)]


# --- Rule A: Israeli aircraft only ----------------------------------------
# Presence of any of these means the text names Israel as the operator, so
# rule A does not apply even when another party is also mentioned ("الطيران
# الإسرائيلي فوق مقر اليونيفيل" is an Israeli violation, not a UNIFIL flight).
_ISRAELI_ATTRIBUTION_TERMS = (
    "اسرائيل", "اسرائيلي", "اسرائيليه", "الاحتلال", "احتلال", "العدو", "عدو",
    "صهيوني", "الصهيوني", "معادي", "معاديه", "معاد", "israeli", "israel",
    "idf", "enemy",
)
# Parties that never operate the aircraft in an Israeli air-violation report,
# so naming them at all is an attribution.
_UNAMBIGUOUS_NON_ISRAELI_PARTIES = (
    "يونيفيل", "يونيفل", "unifil", "unfil", "unifl",
    "قوات الدوليه", "قوات دوليه", "قوات الطوارئ الدوليه", "قوات الطوارئ",
    "امم المتحده", "united nations", "صليب الاحمر", "red cross",
    "طيران الجيش", "مروحيه الجيش",
)
# Parties that are routinely *quoted* in an Israeli air-violation report
# ("the Lebanese army announced that Israeli aircraft..."), so these only
# count inside an explicit attribution construction.
_AMBIGUOUS_NON_ISRAELI_PARTIES = (
    "جيش اللبناني", "دفاع المدني", "قوي الامن الداخلي",
    "lebanese army", "civil defence", "civil defense",
)
_ATTRIBUTION_MARKER_RE = re.compile(r"تابع(?:ه|ين|ون|ات)?\s*ل")

_ISRAELI_ATTRIBUTION_COMPILED = _compile_tokens(_ISRAELI_ATTRIBUTION_TERMS)
_UNAMBIGUOUS_PARTIES_COMPILED = _compile_tokens(_UNAMBIGUOUS_NON_ISRAELI_PARTIES)
_AMBIGUOUS_PARTIES_COMPILED = _compile_tokens(_AMBIGUOUS_NON_ISRAELI_PARTIES)
_AIRCRAFT_COMPILED = _compile_tokens(_AIRCRAFT_TERMS)


# --- Rule B: denials and clarifications -----------------------------------
# A negation only counts when what it negates is the aircraft or the strike.
# "لا يوجد غارة مروحية" denies the event; "لا يوجد ماء في البلدة" does not.
_NEGATION_TERMS = (
    "لا يوجد", "لا توجد", "لا وجود", "ليس هناك", "ليست هناك", "لا صحه",
    "لم يحدث", "لم تحدث", "لم يكن هناك",
    "نفي", "ينفي", "تنفي", "شائعه", "شائعات",
)
# Negations that follow the claim they deny: "خبر الغارة غير صحيح".
_TRAILING_NEGATION_TERMS = (
    "غير صحيح", "غير صحيحه", "خبر كاذب", "عاري عن الصحه", "لا اساس له",
)
# Markers that name what they deny, so nothing else needs to be in scope.
_SELF_CONTAINED_NEGATION_TERMS = (
    "لا طيران", "ليس غاره", "ليست غاره", "لا غاره", "لا غارات",
)
# A clarification labels the whole post as being *about* a report rather than
# reporting an event, so its scope is the post, not a clause.
_CLARIFICATION_TERMS = (
    "تنويه", "توضيح", "للتوضيح", "اقتضي التوضيح", "تصحيح", "نعتذر", "استدراك",
)
# An affirmative sentence about civilian aviation is not an air violation, so
# it can never rescue a denial into "held for review".
_CIVILIAN_AVIATION_TERMS = ("طيران مدني", "طيران تجاري", "رحلات مدنيه", "طيران الركاب")
#: How far after a negation marker its scope reaches, in characters. Long
#: enough for "ولا يوجد أي طيران حربي", short enough not to span a sentence.
_NEGATION_SCOPE_CHARS = 60
_CLAUSE_BOUNDARY_RE = re.compile(r"[.،؛:!؟\n]|(?<=\s)(?:لكن|الا ان|غير ان|بينما)(?=\s)")

_NEGATED_SUBJECT_TERMS = _AIRCRAFT_TERMS + _STRIKE_TERMS
_NEGATED_SUBJECT_COMPILED = _compile_tokens(_NEGATED_SUBJECT_TERMS)
_CIVILIAN_AVIATION_COMPILED = _compile_tokens(_CIVILIAN_AVIATION_TERMS)
_CLARIFICATION_COMPILED = _compile_tokens(_CLARIFICATION_TERMS)


# --- Rule D: generic country-level direction -------------------------------
_GENERIC_DIRECTION_PHRASES = (
    "اتجاه لبنان", "باتجاه لبنان", "نحو لبنان", "فوق لبنان", "في لبنان",
    "داخل لبنان", "اجواء لبنان", "الاجواء اللبنانيه", "اجواء لبنانيه",
    "toward lebanon", "towards lebanon", "over lebanon", "to lebanon",
)
# Red Alert posts carry a fixed footer and, for image alerts, OCR furniture.
# None of it is a location.
_LOCATION_BOILERPLATE = (
    "الخريطه المباشره", "الخريطه المباشر", "لمتابعه المزيد من التفاصيل",
    "الموقع بحاجه الي التحقق", "اقصي درجات الحذر", "حيطه وحذر",
    "redalert.com.lb", "redalert.com.ib", "__red_zone_text__",
)
# A named region is a location even without a village, so these keep a row out
# of rule D: "#الجنوب" is a recognised designation, bare "لبنان" is not.
_REGION_DESIGNATION_TERMS = (
    "الجنوب", "جنوب لبنان", "البقاع", "بقاع", "الشمال", "شمال لبنان",
    "جبل لبنان", "الضاحيه", "ضاحيه", "القطاع الغربي", "القطاع الشرقي",
    "القطاع الاوسط", "south lebanon", "north lebanon", "bekaa", "beqaa",
    "mount lebanon",
)
# A location marker is always followed by a name, so its presence means a
# place was named even when this module cannot resolve it.
_LOCATION_MARKER_TERMS = (
    "قضاء", "بلده", "مدينه", "منطقه", "مخيم", "مزرعه", "اطراف", "محيط",
    "ضهر", "وادي", "جرود", "تله", "خربه", "عين", "دير", "برج",
)
# Vocabulary that is never a place: aircraft, flight verbs, alert furniture
# and ordinary function words. Whatever survives removing all of it is a
# candidate place name, so an unknown word keeps rule D from firing. That
# fails safe: the row falls through to rule E and a human, not to a reject.
_NON_LOCATION_TOKENS = frozenset(
    normalize_arabic_text(token).casefold()
    for token in (
        # aircraft
        "طيران", "طائره", "طائرات", "مقاتلات", "مقاتله", "حربي", "حربيه",
        "مسيره", "مسيرات", "مسير", "مروحيه", "مروحي", "استطلاعي", "استطلاع",
        "درون", "هليكوبتر", "تجسس", "اباتشي", "زنانه",
        # flight and direction
        "تحليق", "يحلق", "تحلق", "تحوم", "تحويم", "حلقت", "اتجاه", "باتجاه",
        "نحو", "فوق", "عبر", "مرور", "خرق", "تركيز", "رصد", "رصدت", "تحرك",
        "دخول", "مغادره", "عوده", "محلق", "محلقه", "اجواء", "الاجواء",
        "اجوائنا", "سماء", "السماء",
        # alert furniture
        "تنبيه", "تنبيهات", "عاجل", "انذار", "حذر", "حيطه", "اقصي", "درجات",
        "الخريطه", "خريطه", "المباشره", "مباشره", "المباشر", "الموقع", "موقع",
        "بحاجه", "التحقق", "تحقق", "لمتابعه", "متابعه", "المزيد", "التفاصيل",
        "تفاصيل", "alert", "redalert", "red", "map", "live", "lb", "ib",
        # the country itself is the generic location rule D rejects
        "لبنان", "اللبنانيه", "لبنانيه", "lebanon", "lebanese",
        # function words
        "في", "علي", "عن", "الي", "من", "هو", "هي", "ان", "اي",
        "مع", "او", "ثم", "قد", "كل", "هذا", "هذه", "التي", "الذي", "لا",
        "ما", "تم", "يتم", "حيث", "بين", "عند", "الان", "الليله", "اليوم",
        "صباحا", "مساء", "ظهرا", "ليلا", "فجرا", "صباح", "مساءا",
        # place descriptors: they mark that a place follows, they are not its
        # name, so they must not be offered as the unmatched name in rule E.
        "قضاء", "بلده", "البلده", "مدينه", "المدينه", "منطقه", "المنطقه",
        "مخيم", "مزرعه", "اطراف", "محيط", "قري", "القري", "بلدات",
    )
)
_LETTER_TOKEN_RE = re.compile(rf"{_ARABIC_LETTER}{{2,}}")

_REGION_DESIGNATION_COMPILED = _compile_tokens(_REGION_DESIGNATION_TERMS)
_LOCATION_MARKER_COMPILED = _compile_tokens(_LOCATION_MARKER_TERMS)


def _unwrap_hashtags(value: str) -> str:
    return _HASHTAG_RE.sub(lambda match: " " + match.group(0)[1:].replace("_", " "), value)


def _strip_source_noise(value: str, *, keep_hashtags: bool = False) -> str:
    value = _URL_RE.sub(" ", value)
    value = _unwrap_hashtags(value) if keep_hashtags else _HASHTAG_RE.sub(" ", value)
    value = _HANDLE_RE.sub(" ", value)
    kept: list[str] = []
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if not line or _TITLE_LINE_RE.match(line):
            continue
        line = _LEADING_SOURCE_RE.sub("", line)
        line = _HONORIFIC_PREFIX_RE.sub("", line)
        if line.strip():
            kept.append(line.strip())
    return "\n".join(kept)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", normalize_arabic_text(value).casefold()).strip()


def _clean_with_provenance(text: str | None) -> tuple[str, bool]:
    """Return the matchable text and whether it came only from hashtags.

    Hashtags are dropped because trailing tag lists ("#شهيد") label a feed
    rather than reporting an event. Red Alert posts are hashtags only, though,
    so when dropping them would leave nothing the tags are unwrapped and kept
    as the content -- and the caller is told, because a bare "#الشهيد" is a
    label, not a casualty report.
    """
    raw = text or ""
    cleaned = _normalize(_strip_source_noise(raw))
    if cleaned:
        return cleaned, False
    return _normalize(_strip_source_noise(raw, keep_hashtags=True)), True


def cleaned_air_violation_text(text: str | None) -> str:
    return _clean_with_provenance(text)[0]


def location_evidence_text(text: str | None) -> str:
    """The text to read a location out of, with hashtags always kept.

    A Red Alert post names its region only in a tag ("#الجنوب"), and that tag
    is a recognised designation. Dropping it, as the event-text cleaner does,
    would make a regional alert look location-free.
    """
    return _normalize(_strip_source_noise(text or "", keep_hashtags=True))


def _matched_terms(text: str, terms: tuple[str, ...]) -> list[str]:
    return list(dict.fromkeys(term for term in terms if term.casefold() in text))


def _has_concrete_lebanese_violation(text: str) -> bool:
    if not any(term in text for term in ("فوق", "في اجواء", "داخل الاجواء", "يحلق فوق", "تحليق فوق")):
        return False
    if resolve_caza_alias(text):
        return True
    return any(marker in text for marker in ("قضاء", "بلده", "مدينه", "الجنوب", "لبنان"))


def _non_israeli_attribution(text: str) -> list[str]:
    """Rule A: terms attributing the aircraft to a party other than Israel."""
    if not _matched_tokens(text, _AIRCRAFT_COMPILED):
        return []
    if _matched_tokens(text, _ISRAELI_ATTRIBUTION_COMPILED):
        # Israel is named as the operator; another party mentioned alongside
        # is context (a UNIFIL base overflown, an army statement quoted).
        return []
    unambiguous = _matched_tokens(text, _UNAMBIGUOUS_PARTIES_COMPILED)
    if unambiguous:
        return unambiguous
    ambiguous = _matched_tokens(text, _AMBIGUOUS_PARTIES_COMPILED)
    if ambiguous and _ATTRIBUTION_MARKER_RE.search(text):
        return ambiguous
    return []


def _forward_scope(text: str, end: int) -> int:
    scope_end = min(len(text), end + _NEGATION_SCOPE_CHARS)
    boundary = _CLAUSE_BOUNDARY_RE.search(text, end, scope_end)
    return boundary.start() if boundary is not None else scope_end


def _backward_scope(text: str, start: int) -> int:
    scope_start = max(0, start - _NEGATION_SCOPE_CHARS)
    for boundary in _CLAUSE_BOUNDARY_RE.finditer(text, scope_start, start):
        scope_start = boundary.end()
    return scope_start


def _denial_scopes(text: str) -> list[tuple[str, int, int]]:
    """Negation markers whose scope contains an aircraft or strike word.

    Direction is a property of the marker, not a window around it. A leading
    negation denies what follows it ("لا يوجد غارة مروحية"); a trailing one
    denies what precedes it ("خبر الغارة غير صحيح"). Reading both ways for
    every marker would let "تحليق طيران حربي فوق الخيام ولا يوجد أي أضرار"
    look like a denial of the flight, when it denies only the damage.

    Returns ``(term, clause_start, clause_end)`` so the caller can strip the
    denied clause and ask what the rest of the post still claims.
    """
    scopes: list[tuple[str, int, int]] = []
    for term in _SELF_CONTAINED_NEGATION_TERMS:
        for match in _token_pattern(term).finditer(text):
            # The marker names what it denies ("لا طيران"), so there is
            # nothing further to look for.
            scopes.append((term, match.start(), _forward_scope(text, match.end())))
    for term in _NEGATION_TERMS:
        for match in _token_pattern(term).finditer(text):
            scope_end = _forward_scope(text, match.end())
            if _matched_tokens(text[match.end():scope_end], _NEGATED_SUBJECT_COMPILED):
                scopes.append((term, match.start(), scope_end))
    for term in _TRAILING_NEGATION_TERMS:
        for match in _token_pattern(term).finditer(text):
            scope_start = _backward_scope(text, match.start())
            if _matched_tokens(text[scope_start:match.start()], _NEGATED_SUBJECT_COMPILED):
                scopes.append((term, scope_start, match.end()))
    return scopes

def _remaining_claim(text: str, scopes: list[tuple[str, int, int]]) -> str:
    """The post with every denied clause removed."""
    remaining = text
    for _term, start, end in sorted(scopes, key=lambda scope: scope[1], reverse=True):
        remaining = remaining[:start] + " " + remaining[end:]
    return re.sub(r"\s+", " ", remaining).strip()


def _denial_or_clarification(text: str) -> tuple[list[str], bool]:
    """Rule B: ``(matched terms, also reports a real overflight)``.

    The second value is what separates a reject from a hold: a post that
    denies one thing and *also* reports an Israeli overflight somewhere else
    is ambiguous and goes to a human.
    """
    scopes = _denial_scopes(text)
    clarifications = (
        _matched_tokens(text, _CLARIFICATION_COMPILED)
        if _matched_tokens(text, _NEGATED_SUBJECT_COMPILED)
        else []
    )
    matched = list(dict.fromkeys([term for term, _s, _e in scopes] + clarifications))
    if not matched:
        return [], False
    if _matched_tokens(text, _CIVILIAN_AVIATION_COMPILED):
        # "the aircraft heard was civilian" affirms nothing this system logs.
        return matched, False
    remaining = _remaining_claim(text, scopes)
    also_reports_overflight = bool(
        _matched_tokens(remaining, _ISRAELI_ATTRIBUTION_COMPILED)
        and _matched_tokens(remaining, _AIRCRAFT_COMPILED)
        and _has_concrete_lebanese_violation(remaining)
    )
    return matched, also_reports_overflight


def has_region_designation(location_text: str) -> bool:
    """True when a named region or caza stands in for a village (rule C).

    A بلدة or a مدينة does not count: those name a village, and a village
    that resolved to nothing is rule E, not an accepted regional alert.
    """
    return bool(
        _matched_tokens(location_text, _REGION_DESIGNATION_COMPILED)
        or resolve_caza_alias(location_text)
    )


def names_a_place(location_text: str) -> bool:
    """True when the text names *something*, resolvable or not.

    This is the test rule D inverts. A place marker or an unrecognised word
    both count, so rule D only fires when there is genuinely nothing to look
    up and the row instead falls to rule E.
    """
    return bool(
        has_region_designation(location_text)
        or _matched_tokens(location_text, _LOCATION_MARKER_COMPILED)
        or _residual_location_words(location_text)
    )


def _residual_location_words(location_text: str) -> list[str]:
    """Words left after removing everything that cannot be a place name."""
    stripped = location_text
    for phrase in (*_GENERIC_DIRECTION_PHRASES, *_LOCATION_BOILERPLATE):
        stripped = stripped.replace(normalize_arabic_text(phrase).casefold(), " ")
    return list(dict.fromkeys(
        word
        for word in _LETTER_TOKEN_RE.findall(stripped)
        if word not in _NON_LOCATION_TOKENS
    ))


def generic_direction_only(location_text: str) -> list[str]:
    """Rule D: the matched generic phrases when the text names no place.

    Fails safe. An unrecognised word is treated as a possible place name, so
    an unexpected post falls through to rule E and a human rather than being
    rejected on a vocabulary gap.
    """
    if names_a_place(location_text):
        return []
    matched = _matched_terms(location_text, _GENERIC_DIRECTION_PHRASES) or _matched_terms(
        location_text, _LOCATION_BOILERPLATE
    )
    return matched


def evaluate_air_violation_text(text: str | None) -> EligibilityResult:
    """Decide whether text describes presence-only air activity."""
    cleaned, hashtags_only = _clean_with_provenance(text)
    if not cleaned:
        return EligibilityResult(False, "empty_text", [])

    status_terms = _matched_terms(cleaned, _STATUS_UPDATE_TERMS)
    if status_terms:
        return EligibilityResult(False, "excluded_red_alert_status_update", status_terms)

    notice_terms = _matched_terms(cleaned, _NON_EVENT_NOTICE_TERMS)
    if notice_terms:
        return EligibilityResult(False, "excluded_non_event_notice", notice_terms)

    # Rule A. An air violation is an Israeli aircraft in Lebanese airspace.
    attribution_terms = _non_israeli_attribution(cleaned)
    if attribution_terms:
        return EligibilityResult(False, NON_ISRAELI_REASON, attribution_terms)

    # Rule B. A denial or a clarification reports that nothing happened.
    denial_terms, also_reports_overflight = _denial_or_clarification(cleaned)
    if denial_terms:
        if also_reports_overflight:
            return EligibilityResult(
                False, DENIAL_WITH_OVERFLIGHT_REASON, denial_terms
            )
        return EligibilityResult(False, DENIAL_REASON, denial_terms)

    route_terms = _matched_terms(cleaned, ("من فلسطين باتجاه", "من فلسطين نحو", "from palestine toward", "from palestine to"))
    if route_terms and _matched_tokens(cleaned, _AIRCRAFT_COMPILED) and not _has_concrete_lebanese_violation(cleaned):
        return EligibilityResult(False, "excluded_origin_route_palestine", route_terms)

    matchable = _KINETIC_LOOKALIKE_RE.sub(" ", cleaned)
    strike_terms = _matched_terms(matchable, _STRIKE_TERMS)
    casualty_terms = _matched_terms(matchable, _CASUALTY_TERMS)
    damage_terms = _matched_terms(matchable, _DAMAGE_TERMS)
    fire_terms = _matched_terms(matchable, _FIRE_TERMS) if strike_terms else []
    apache_terms = _matched_terms(matchable, _APACHE_TERMS) if strike_terms else []
    rejected_terms = list(dict.fromkeys([
        *strike_terms,
        *casualty_terms,
        *damage_terms,
        *fire_terms,
        *apache_terms,
    ]))
    if rejected_terms:
        if hashtags_only:
            # The only evidence is a bare tag ("#الشهيد"), which labels a feed
            # and reports nothing. Too thin to call an incident, so it goes to
            # a human rather than into the incident pipeline.
            return EligibilityResult(False, "excluded_hashtag_only_ambiguous", rejected_terms)
        return EligibilityResult(False, KINETIC_EXCLUSION_REASON, rejected_terms)

    # Rule D. "Toward Lebanon" names no place, and neither does a bare map
    # link. Checked after the kinetic terms so a strike report with no
    # location still reaches the incident pipeline.
    direction_terms = generic_direction_only(location_evidence_text(text))
    if direction_terms:
        return EligibilityResult(False, GENERIC_DIRECTION_REASON, direction_terms)

    return EligibilityResult(True, "presence_only", [])


def evaluate_air_violation_location(
    text: str | None,
    *,
    has_resolved_village: bool,
    caza_label: str | None = None,
    unmatched_names: tuple[str, ...] = (),
) -> EligibilityResult:
    """Rules C and E: an air violation needs a place.

    Call this only once :func:`evaluate_air_violation_text` returned eligible.
    A resolved village always passes. With no village, a recognised region
    designation still passes -- that is what keeps a legitimate multi-region
    Warplane alert working. Everything else is rule D (no location at all) or
    rule E (a place was named and resolved to nothing).
    """
    if has_resolved_village:
        return EligibilityResult(True, "presence_only", [])

    location_text = location_evidence_text(text)
    direction_terms = generic_direction_only(location_text)
    if direction_terms:
        return EligibilityResult(False, GENERIC_DIRECTION_REASON, direction_terms)

    if caza_label and caza_label.strip() and caza_label.strip() != "Unknown":
        return EligibilityResult(True, "presence_only", [])
    if has_region_designation(location_text):
        return EligibilityResult(True, "presence_only", [])

    candidates = [name.strip() for name in unmatched_names if name and name.strip()]
    if not candidates:
        candidates = _residual_location_words(location_text)
    if not candidates:
        # No village, no region, and nothing that could be a place name.
        return EligibilityResult(False, GENERIC_DIRECTION_REASON, [])
    return EligibilityResult(
        False, UNMATCHED_LOCATION_REASON, candidates[:5], unmatched_location=candidates[0]
    )
