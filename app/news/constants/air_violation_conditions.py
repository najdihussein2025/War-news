"""Canonical air-violation condition IDs and counting vocabulary.

Condition 45 is intentionally excluded. It is a Red Alert internal fallback for
unclassified air activity and should not be treated as a routable air violation.
"""

AIR_VIOLATION_SPY_BALLOON_CONDITION_ID = 34
AIR_VIOLATION_WARPLANE_CONDITION_ID = 35
AIR_VIOLATION_DRONE_CONDITION_ID = 36
AIR_VIOLATION_HELICOPTER_CONDITION_ID = 38
AIR_VIOLATION_CONDITION_IDS = frozenset({
    AIR_VIOLATION_SPY_BALLOON_CONDITION_ID,
    AIR_VIOLATION_WARPLANE_CONDITION_ID,
    AIR_VIOLATION_DRONE_CONDITION_ID,
    AIR_VIOLATION_HELICOPTER_CONDITION_ID,
})
AIR_VIOLATION_CONDITION_ID_TUPLE = tuple(sorted(AIR_VIOLATION_CONDITION_IDS))

# CNRS methodology: drone reports in these cazas are counted in anchored 6-hour
# windows; every other caza counts once per Beirut calendar day. Names are the
# canonical spellings produced by ``canonicalize_caza``.
DRONE_SIX_HOUR_CAZAS = frozenset({
    "Baabda",
    "Baalbek",
    "Bint Jubail",
    "Hermel",
    "Jezzine",
    "Marjaayoun",
    "Nabatiye",
    "Saida",
    "Sour",
    "West Bekaa",
})

# Caza -> mohafaza, using the mohafaza spellings stored on ``villages``. Keys are
# canonical caza names. Used to place a warplane report that names no village.
CAZA_TO_MOHAFAZA: dict[str, str] = {
    "Aley": "Mount Lebanon",
    "Baabda": "Mount Lebanon",
    "Chouf": "Mount Lebanon",
    "El Metn": "Mount Lebanon",
    "Jubail": "Mount Lebanon",
    "Kasrouane": "Mount Lebanon",
    "Jezzine": "South",
    "Saida": "South",
    "Sour": "South",
    "Zahrani": "South",
    "Bint Jubail": "Nabatiye",
    "Hasbaya": "Nabatiye",
    "Marjaayoun": "Nabatiye",
    "Nabatiye": "Nabatiye",
    "Baalbek": "Baalbek_Hermel",
    "Hermel": "Baalbek_Hermel",
    "Rachiaya": "Bekaa",
    "West Bekaa": "Bekaa",
    "Zahle": "Bekaa",
    "Batroun": "North",
    "Bcharre": "North",
    "Koura": "North",
    "Minieh-Danieh": "North",
    "Tripoli": "North",
    "Zgharta": "North",
    "Akkar": "Akkar",
    "Beirut": "Beirut",
}

# Legacy window list, removed once window_grouping_service is retired.
AIR_VIOLATION_SOUTH_CAZAS = frozenset(DRONE_SIX_HOUR_CAZAS | {"Hasbaya", "Zahrani"})
