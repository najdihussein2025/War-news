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
# Seeded aliases (Data/VillageLocationAliases.json). Parent choice notes:
#   Nabatieh Et-Tahta (ACS 71111) = caza seat for مدينة النبطية / حي المسلخ.
#   Nabatiyeh El-Faouka (ACS 71113) = only when that municipality is named.
#   Additional rows mined from the 89 distinct cross-village RM pairs (14d).
# Schema has caza/mohafaza labels but no parent FK — aliases are the mechanism.
# ---------------------------------------------------------------------------
PROPOSED_VILLAGE_LOCATION_ALIASES: tuple[VillageLocationAliasProposal, ...] = (
    VillageLocationAliasProposal(
        alias_text="النبطية",
        parent_acs_code=71111,
        note="Bare city/caza-seat mention → Nabatieh Et-Tahta.",
        confidence="proposed",
        evidence="recon 2026-09-07 Douair 0.615 ال-suffix trap",
    ),
    VillageLocationAliasProposal(
        alias_text="مدينة النبطية",
        parent_acs_code=71111,
        note="Explicit city phrasing → Nabatieh Et-Tahta.",
        confidence="proposed",
        evidence="recon 2026-09-07 Zibdine 0.474",
    ),
    VillageLocationAliasProposal(
        alias_text="حي المسلخ",
        parent_acs_code=71111,
        note="Nabatiyeh-city neighborhood → Et-Tahta, not Masqa.",
        confidence="proposed",
        evidence="recon maslakh cluster; Masqa is المتن",
    ),
    VillageLocationAliasProposal(
        alias_text="المسلخ",
        parent_acs_code=71111,
        note="Extractor often strips حي.",
        confidence="proposed",
        evidence="recon المسلخ → Masqa 0.40",
    ),
    VillageLocationAliasProposal(
        alias_text="محيط النبطية الفوقا",
        parent_acs_code=71113,
        note="Descriptor+name → El-Faouka.",
        confidence="proposed",
        evidence="14d Houmine 703 vs Douair 543 split",
    ),
    VillageLocationAliasProposal(
        alias_text="دوحة كفررمان",
        parent_acs_code=71133,
        note="Compound of Kfar Roummane.",
        confidence="proposed",
        evidence="89-pair backlog: 21 msgs low-confidence → 851",
    ),
    VillageLocationAliasProposal(
        alias_text="وادي زبقين",
        parent_acs_code=62286,
        note="Valley-of-village → Zebqine.",
        confidence="proposed",
        evidence="89-pair backlog: 9 msgs low-confidence → 1523",
    ),
    VillageLocationAliasProposal(
        alias_text="حرش كونين",
        parent_acs_code=72251,
        note="Grove + village → Kounine.",
        confidence="proposed",
        evidence="89-pair backlog: 3 msgs",
    ),
    VillageLocationAliasProposal(
        alias_text="حرش علي الطاهر",
        parent_acs_code=71115,
        note="Grove + village → Aali Et-Taher.",
        confidence="proposed",
        evidence="89-pair backlog: 3 msgs",
    ),
    VillageLocationAliasProposal(
        alias_text="محيط المنصوري",
        parent_acs_code=62296,
        note="Outskirts → Mansouri Sour.",
        confidence="proposed",
        evidence="89-pair backlog: المنصوري top non-Nabatiyeh (26 msgs)",
    ),
    VillageLocationAliasProposal(
        alias_text="أطراف المنصوري",
        parent_acs_code=62296,
        note="Outskirts → Mansouri Sour.",
        confidence="proposed",
        evidence="bulletin phrasing with المنصوري",
    ),
    VillageLocationAliasProposal(
        alias_text="محيط علي الطاهر",
        parent_acs_code=71115,
        note="Outskirts → Aali Et-Taher.",
        confidence="proposed",
        evidence="89-pair backlog: علي الطاهر in 10 msgs",
    ),
    VillageLocationAliasProposal(
        alias_text="أطراف علي الطاهر",
        parent_acs_code=71115,
        note="Outskirts → Aali Et-Taher.",
        confidence="proposed",
        evidence="bulletin phrasing with علي الطاهر",
    ),
    VillageLocationAliasProposal(
        alias_text="القنطرة",
        parent_acs_code=73276,
        note="Marjayoun قنطرة, not Akkar Qantarat.",
        confidence="proposed",
        evidence="89-pair backlog: 11 msgs → Akkar 1229; correct ACS 73276",
    ),
    VillageLocationAliasProposal(
        alias_text="عيناثا",
        parent_acs_code=72119,
        note="Aaynata Bent Jbayl, not Metn Aaynab.",
        confidence="proposed",
        evidence="89-pair backlog: 4 msgs → 142 Aaynab; ACS 72119",
    ),
    VillageLocationAliasProposal(
        alias_text="عيناتا",
        parent_acs_code=72119,
        note="Spelling variant → Aaynata Bent Jbayl (war-news default).",
        confidence="proposed",
        evidence="Baalbek عيناتا also exists; southern usage dominates backlog",
    ),
    VillageLocationAliasProposal(
        alias_text="المجيدية",
        parent_acs_code=74177,
        note="Majidiye Hasbaya, not Massaaoudiyé Akkar.",
        confidence="proposed",
        evidence="89-pair backlog: 2 msgs → 998; ACS 74177",
    ),
    VillageLocationAliasProposal(
        alias_text="حاروف",
        parent_acs_code=71331,
        note="Common Arabic spelling → Harouf En-Nabatiyeh.",
        confidence="proposed",
        evidence="Road bulletin spelling; ACS ref_name_ar stores حروف.",
    ),
)

# Flagged uncertain — do NOT seed until reviewed with more evidence.
UNCERTAIN_VILLAGE_LOCATION_ALIAS_NOTES: tuple[str, ...] = (
    "وادي السلوقي / السلوقي: fuzzy hits Ouadi Es-Sitt (Chouf) or Slouqi (Baalbek); "
    "neither is the south-Lebanon Saluqi valley. No reliable ACS parent found.",
    "وادي الحجير / الحجير: no ACS village entry; fuzzy hits unrelated Ouadi Ed-Deir.",
    "الفوقا (bare): three-way tie Houmine / Nabatiyeh El-Faouka / Temnine — too ambiguous.",
    "بسطرة: unmatched; no ACS row found.",
    "بين الحنية و المنصوري (and similar between-X-and-Y): multi-location, not a single parent.",
    "Generic descriptor strip (محيط/أطراف/حرش/وادي) remains a separate pending task; "
    "only evidence-backed full phrases are seeded.",
)
