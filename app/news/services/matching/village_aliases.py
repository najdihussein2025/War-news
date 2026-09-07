"""Neighborhood / city-mention aliases that resolve to a parent village.

Mirrors the evidence-backed catalog style of ``condition_aliases.py``, but
persists rows in ``village_location_aliases`` (migration + seed) so matching
can resolve exact normalized mentions to a canonical ``villages`` row without
creating a fake ACS village for every neighborhood.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class VillageLocationAliasProposal:
    """Proposed seed row. ``parent_acs_code`` is the stable key across envs."""

    alias_text: str
    parent_acs_code: int
    note: str
    confidence: str  # "proposed" | "uncertain"
    evidence: str


# ---------------------------------------------------------------------------
# Proposed for seed (review before apply). Parent choice:
#   Nabatieh Et-Tahta (ACS 71111) = caza seat / main city for "مدينة النبطية".
#   Nabatiyeh El-Faouka (ACS 71113) = only when that municipality is named.
# Schema has caza/mohafaza labels but no parent FK — aliases are the mechanism.
# ---------------------------------------------------------------------------
PROPOSED_VILLAGE_LOCATION_ALIASES: tuple[VillageLocationAliasProposal, ...] = (
    VillageLocationAliasProposal(
        alias_text="النبطية",
        parent_acs_code=71111,
        note="Bare city/caza-seat mention → Nabatieh Et-Tahta (not a new village row).",
        confidence="proposed",
        evidence="recon 2026-09-07: النبطية fuzzy-matched Douair (543) at 0.615 via ال-suffix trap",
    ),
    VillageLocationAliasProposal(
        alias_text="مدينة النبطية",
        parent_acs_code=71111,
        note="Explicit city phrasing → Nabatieh Et-Tahta.",
        confidence="proposed",
        evidence="recon 2026-09-07: مدينة النبطية fuzzy-matched Zibdine (1529) at 0.474",
    ),
    VillageLocationAliasProposal(
        alias_text="حي المسلخ",
        parent_acs_code=71111,
        note="Nabatiyeh-city neighborhood → parent city seat (Et-Tahta), not Masqa.",
        confidence="proposed",
        evidence="recon 2026-09-07 maslakh cluster; Masqa (995) is المتن/جبل لبنان",
    ),
    VillageLocationAliasProposal(
        alias_text="المسلخ",
        parent_acs_code=71111,
        note="Extractor often strips حي; same parent as حي المسلخ.",
        confidence="proposed",
        evidence="recon: extracted raw_village_text=المسلخ → Masqa 0.40",
    ),
    VillageLocationAliasProposal(
        alias_text="محيط النبطية الفوقا",
        parent_acs_code=71113,
        note="Descriptor+name compound seen splitting Houmine vs Douair; pin to El-Faouka.",
        confidence="proposed",
        evidence="14d scope: identical قصف محيط النبطية الفوقا → Houmine 703 vs Douair 543",
    ),
)

# Flagged uncertain — do NOT seed until reviewed with more evidence.
UNCERTAIN_VILLAGE_LOCATION_ALIAS_NOTES: tuple[str, ...] = (
    "Other Nabatiyeh neighborhoods from multi-location daily summaries were not "
    "added — those are expected multi-village materializations, not city aliases.",
    "Whether any 'النبطية' mentions should prefer El-Faouka over Et-Tahta when the "
    "text also says الفوقا is handled by the separate النبطية الفوقا / محيط alias; "
    "bare النبطية stays Et-Tahta.",
    "Generic descriptor strip (محيط/أطراف/حرش) remains a separate pending task; "
    "only evidence-backed full phrases are proposed here.",
)
