from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(frozen=True)
class EvidenceSpan:
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class NormalizedText:
    text: str
    offsets: tuple[int, ...]
    original: str

    def original_span(self, start: int, end: int) -> EvidenceSpan:
        if start >= end or not self.offsets:
            return EvidenceSpan(start=0, end=0, text="")
        left = self.offsets[max(0, start)]
        right = self.offsets[min(end - 1, len(self.offsets) - 1)] + 1
        return EvidenceSpan(left, right, self.original[left:right])


@dataclass(frozen=True)
class SummaryDetection:
    is_summary: bool
    markers: tuple[str, ...]
    header_count: int
    segment_count: int
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class SummaryWindow:
    start: datetime
    end: datetime
    rule: str
    evidence: str | None
    anchor_date: date
    note: str | None = None


@dataclass(frozen=True)
class VillageRef:
    id: int
    name_ar: str
    caza: str
    coord_x: float | None = None
    coord_y: float | None = None
    place_detail: str | None = None


@dataclass(frozen=True)
class HeaderEntry:
    normalized_header: str
    condition_ids: tuple[int, ...]
    status: str
    note: str = ""


@dataclass(frozen=True)
class ParsedSummaryItem:
    condition_id: int
    primary_village: VillageRef
    secondary_village: VillageRef | None
    qualifiers: tuple[str, ...]
    place_detail: str | None
    reported_count: int
    location_texts: tuple[str, ...]
    evidence_spans: tuple[EvidenceSpan, ...]
    header_text: str
    item_key: str
    event_time: datetime | None = None
    origin_text: str | None = None
    status: str = "resolved"


@dataclass(frozen=True)
class SummaryResidual:
    kind: str
    text: str
    section_header: str | None
    offsets: tuple[int, int]


@dataclass(frozen=True)
class ParsedSection:
    header_text: str
    condition_ids: tuple[int, ...]
    location_text: str


@dataclass(frozen=True)
class ParseResult:
    sections: tuple[ParsedSection, ...]
    items: tuple[ParsedSummaryItem, ...]
    leftover_tokens: tuple[str, ...] = field(default_factory=tuple)
    unresolved_headers: tuple[str, ...] = field(default_factory=tuple)
    unresolved_places: tuple[str, ...] = field(default_factory=tuple)
    ambiguous_places: tuple[str, ...] = field(default_factory=tuple)
    out_of_scope_lines: tuple[str, ...] = field(default_factory=tuple)
    auto_acceptable: bool = False
    residual: tuple[SummaryResidual, ...] = field(default_factory=tuple)
    disposition: str = "residual_only"
