from __future__ import annotations

from dataclasses import dataclass
import re

from app.core.text_normalization import normalize_arabic_text
from app.llm.dtos import CasualtyScope, VillageRole, VillageRoleEntry


@dataclass(frozen=True)
class CasualtyScopeBackstopResult:
    plausible: bool
    matched_village_names: tuple[str, ...]
    village_count_in_evidence: int


def _phrase_occurrences(text: str, phrase: str) -> list[tuple[int, int]]:
    if not phrase:
        return []
    return [
        match.span()
        for match in re.finditer(
            rf"(?<![\w])(?:و)?{re.escape(phrase)}(?![\w])",
            text,
        )
    ]


def _matched_villages(
    evidence: str,
    village_roles: list[VillageRoleEntry],
    aliases_by_village: dict[str, tuple[str, ...]] | None,
) -> tuple[str, ...]:
    normalized_evidence = normalize_arabic_text(evidence)
    candidates: list[tuple[str, list[str]]] = []
    for entry in village_roles:
        if entry.role != VillageRole.target:
            continue
        variants = [entry.village]
        variants.extend((aliases_by_village or {}).get(entry.village, ()))
        normalized_variants = sorted(
            {
                normalize_arabic_text(variant)
                for variant in variants
                if normalize_arabic_text(variant)
            },
            key=len,
            reverse=True,
        )
        candidates.append((entry.village, normalized_variants))

    occurrences: list[tuple[int, int, str]] = []
    for village_name, variants in candidates:
        for variant in variants:
            occurrences.extend(
                (start, end, village_name)
                for start, end in _phrase_occurrences(normalized_evidence, variant)
            )

    selected: list[tuple[int, int, str]] = []
    for start, end, village_name in sorted(
        occurrences,
        key=lambda item: (-(item[1] - item[0]), item[0], item[2]),
    ):
        if village_name in {item[2] for item in selected}:
            continue
        if any(start < used_end and end > used_start for used_start, used_end, _ in selected):
            continue
        selected.append((start, end, village_name))

    return tuple(
        village_name
        for _, _, village_name in sorted(selected, key=lambda item: item[0])
    )


def validate_casualty_scope(
    *,
    casualty_scope: CasualtyScope,
    evidence: str | None,
    village_roles: list[VillageRoleEntry],
    aliases_by_village: dict[str, tuple[str, ...]] | None = None,
) -> CasualtyScopeBackstopResult:
    if casualty_scope == CasualtyScope.unspecified:
        return CasualtyScopeBackstopResult(
            plausible=True,
            matched_village_names=(),
            village_count_in_evidence=0,
        )
    if not evidence:
        return CasualtyScopeBackstopResult(
            plausible=False,
            matched_village_names=(),
            village_count_in_evidence=0,
        )

    matched = _matched_villages(evidence, village_roles, aliases_by_village)
    if casualty_scope == CasualtyScope.bulletin_aggregate:
        plausible = len(matched) >= 2
    else:
        exact_villages = {
            entry.village
            for entry in village_roles
            if entry.role == VillageRole.target
            and (entry.deaths is not None or entry.injuries is not None)
        }
        plausible = any(name in exact_villages for name in matched)

    return CasualtyScopeBackstopResult(
        plausible=plausible,
        matched_village_names=matched,
        village_count_in_evidence=len(matched),
    )
