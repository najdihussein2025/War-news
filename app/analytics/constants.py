"""Static analytics vocabulary shared by the fact builders and the API."""
from __future__ import annotations

from datetime import date

# Canonical caza name (``canonicalize_caza`` output, i.e. the spelling used by
# villages.caza_en and the breach counting service) -> HDX caza code. Explicit on
# purpose: names drift (Hasbaya/Hasbaiya) and "Akkar" is both a caza and a
# mohafaza, so a name is never compared with another name, only mapped to a code.
CAZA_NAME_TO_CODE: dict[str, str] = {
    "Akkar": "LB51",
    "Aley": "LB31",
    "Baabda": "LB32",
    "Baalbek": "LB21",
    "Batroun": "LB52",
    "Bcharre": "LB53",
    "Beirut": "LB11",
    "Bint Jubail": "LB41",
    "Chouf": "LB33",
    "El Metn": "LB36",
    "Hasbaya": "LB42",
    "Hasbaiya": "LB42",
    "Hermel": "LB22",
    "Jezzine": "LB62",
    "Jubail": "LB34",
    "Kasrouane": "LB35",
    "Koura": "LB54",
    "Marjaayoun": "LB43",
    "Minieh-Danieh": "LB55",
    "Nabatiye": "LB44",
    "Rachiaya": "LB23",
    "Saida": "LB61",
    "Sour": "LB63",
    "Tripoli": "LB56",
    "West Bekaa": "LB24",
    "Zahle": "LB25",
    "Zgharta": "LB57",
}

# Mohafaza name as stored on villages.mohafaza_en (and returned by the breach
# service) -> HDX mohafaza code.
MOHAFAZA_NAME_TO_CODE: dict[str, str] = {
    "Beirut": "LB1",
    "Bekaa": "LB2",
    "Mount Lebanon": "LB3",
    "Nabatiye": "LB4",
    "North": "LB5",
    "South": "LB6",
    "Akkar": "LB7",
    "Baalbek_Hermel": "LB8",
}

# Air-violation condition ids by counting role. Ids are stable across
# environments (they are pinned in app/news/constants/air_violation_conditions.py).
LEVEL_MOHAFAZA = "mohafaza"
LEVEL_CAZA = "caza"
LEVEL_VILLAGE = "village"
LEVELS = (LEVEL_MOHAFAZA, LEVEL_CAZA, LEVEL_VILLAGE)

# Which air condition ids may be mapped at which map level (agreed decision 5).
AIR_LEVEL_CONDITIONS: dict[str, frozenset[int]] = {
    LEVEL_MOHAFAZA: frozenset({34, 35, 36, 38}),
    LEVEL_CAZA: frozenset({34, 36, 38}),
    LEVEL_VILLAGE: frozenset({38}),
}

AIR_CONDITION_LABELS: dict[int, str] = {
    34: "Spy balloons",
    35: "Warplanes",
    36: "Surveillance aircraft / drones",
    38: "Helicopters",
}

MAX_RANGE_DAYS = 400
UNKNOWN_AREA = "unknown"
