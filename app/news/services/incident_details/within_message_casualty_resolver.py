"""Resolve repeated/headline casualty claims inside one source message.

This deliberately never adds claims.  Materialization can use the selected
claim and surface ``conflict_reason`` to its existing verification machinery.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CasualtyClaim:
    deaths: int | None = None
    injuries: int | None = None
    village: str | None = None
    quote: str = ""
    is_headline: bool = False


@dataclass(frozen=True)
class ResolvedCasualties:
    claims: tuple[CasualtyClaim, ...]
    conflict_reason: str | None = None
    aggregate_remainder: CasualtyClaim | None = None


def _sum(values: list[int | None]) -> int | None:
    present = [value for value in values if value is not None]
    return sum(present) if present else None


def resolve_within_message_claims(claims: list[CasualtyClaim]) -> ResolvedCasualties:
    """Prefer location parts; a matching headline is validation, never another toll.

    A headline that does not equal the identified parts is retained as
    ``aggregate_remainder``.  Callers must send it to a bulletin/review path,
    rather than distribute it to a village.
    """
    headlines = [claim for claim in claims if claim.is_headline]
    parts = [claim for claim in claims if not claim.is_headline and claim.village]
    if not parts:
        return ResolvedCasualties(tuple(headlines))
    chosen: dict[str, CasualtyClaim] = {}
    conflicts: list[str] = []
    for part in parts:
        prior = chosen.get(part.village or "")
        if prior is None or prior == part:
            chosen[part.village or ""] = part
            continue
        # Later/specific body claim wins, but preserve both source quotes.
        chosen[part.village or ""] = part
        conflicts.append(f"conflicting tolls for {part.village}: {prior.quote!r} vs {part.quote!r}")
    selected = tuple(chosen.values())
    headline = headlines[0] if headlines else None
    aggregate_remainder = None
    if headline:
        deaths_sum = _sum([item.deaths for item in selected])
        injuries_sum = _sum([item.injuries for item in selected])
        mismatch = (headline.deaths is not None and deaths_sum is not None and headline.deaths != deaths_sum) or (headline.injuries is not None and injuries_sum is not None and headline.injuries != injuries_sum)
        if mismatch:
            conflicts.append(f"headline conflicts with location parts: {headline.quote!r}")
            aggregate_remainder = headline
    return ResolvedCasualties(selected, "; ".join(conflicts) or None, aggregate_remainder)
