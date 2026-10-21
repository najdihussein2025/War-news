"""Realistic synthetic data: hundreds of incidents across all cazas plus air violations of every type."""
from __future__ import annotations

import random
from datetime import date, time, timedelta

from sqlalchemy import text

from tests.analytics.support import BALLOON, DRONE, HELICOPTER, WARPLANE, World

START, END = date(2026, 8, 17), date(2026, 10, 21)
ACTIONS = [("Bombs", 30), ("Artillery Shelling", 40), ("Sweeping Operations", 6), ("Mining & Detonation", 6),
           ("Flare Bomb", 4), ("Drone Failure", 4), ("Tank Fire", 3), ("Shooting", 2), ("Ground Incursion", 2),
           ("Burning Properties", 2), ("Unclassified / Needs Review", 2), ("Air Activity - Needs Verification", 1)]


def populate(world: World, *, incidents: int = 420, air: int = 320, seed: int = 7) -> dict:
    rng = random.Random(seed)
    db = world.db
    villages = [int(r.id) for r in db.execute(text(
        "SELECT id FROM villages WHERE admin_area_code IS NOT NULL ORDER BY id"))]
    # Concentrate activity in the south, like the real data, but touch every caza.
    south = [int(r.id) for r in db.execute(text(
        "SELECT id FROM villages WHERE mohafaza_en IN ('South', 'Nabatiye') AND admin_area_code IS NOT NULL"))]
    names, weights = zip(*ACTIONS)
    days = (END - START).days
    for n in range(incidents):
        pool = south if rng.random() < 0.7 else villages
        status = rng.choices(["auto_processed", "verified", "needs_verification", "rejected"], [88, 3, 7, 2])[0]
        deaths = rng.choices([None, 0, 1, 2, 5], [60, 20, 12, 6, 2])[0]
        injuries = rng.choices([None, 0, 1, 3, 8], [55, 20, 14, 8, 3])[0]
        detail = {}
        if deaths and rng.random() < 0.6:
            detail = {"male_d": rng.randint(0, deaths), "female_d": rng.randint(0, 1)}
        world.incident(
            village_id=rng.choice(pool), condition=rng.choices(names, weights)[0],
            day=START + timedelta(days=rng.randint(0, days)), status=status,
            deleted=rng.random() < 0.08, deaths=deaths, injuries=injuries, commit=False, **detail,
        )
    # one shared bulletin toll, owner incident only
    world.incident(village_id=south[0], condition="Bombs", day=END - timedelta(days=3), deaths=4, injuries=9,
                   casualty_status="aggregate_only", commit=False)
    world.incident(village_id=south[1], condition="Bombs", day=END - timedelta(days=3), commit=False)
    db.commit()

    kinds = [(WARPLANE, 25), (DRONE, 55), (BALLOON, 5), (HELICOPTER, 4)]
    for n in range(air):
        condition_id = rng.choices([k for k, _ in kinds], [w for _, w in kinds])[0]
        day = START + timedelta(days=rng.randint(0, days))
        at = time(rng.randint(0, 23), rng.randint(0, 59))
        if rng.random() < 0.05:
            world.air(condition_id=condition_id, day=day, at=at, commit=False)  # no location
        elif condition_id in (BALLOON,) or rng.random() < 0.15:
            world.air(condition_id=condition_id, day=day, at=at, caza_en=rng.choice(["Sour", "Saida", "Aley", "Zahle"]), commit=False)
        else:
            picks = tuple(rng.sample(south if rng.random() < 0.8 else villages, rng.choice([1, 1, 2])))
            world.air(condition_id=condition_id, day=day, at=at, village_ids=picks, commit=False)
    db.commit()
    return {"incidents": incidents + 2, "air": air}
