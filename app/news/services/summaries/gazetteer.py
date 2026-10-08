from __future__ import annotations

from dataclasses import asdict
from math import hypot
from typing import Iterable, Mapping

from .dtos import VillageRef
from .normalize import normalize_token, village_key

ALLOWED_CAZAS = frozenset({"Bint Jubail", "Hasbaiya", "Jezzine", "Marjaayoun", "Nabatiye", "Saida", "Sour"})


class GazetteerSnapshot:
    def __init__(self, names: Mapping[str, Iterable[VillageRef]], descriptors: Iterable[str] = ()) -> None:
        self.names = {village_key(k): tuple(v) for k, v in names.items() if village_key(k)}
        self.compact_names: dict[str, tuple[VillageRef, ...]] = {}
        for key, values in self.names.items():
            compact = key.replace(" ", "")
            self.compact_names[compact] = tuple(dict.fromkeys(self.compact_names.get(compact, ()) + values))
        self.descriptors = frozenset(normalize_token(x) for x in descriptors)
        self.max_tokens = max((len(k.split()) for k in self.names), default=1)

    def lookup(self, name: str) -> tuple[VillageRef, ...]:
        key = village_key(name)
        return self.names.get(key, self.compact_names.get(key.replace(" ", ""), ()))

    def to_dict(self) -> dict:
        return {"descriptors": sorted(self.descriptors), "names": {k: [asdict(v) for v in values] for k, values in self.names.items()}}

    @classmethod
    def from_dict(cls, payload: dict) -> "GazetteerSnapshot":
        return cls({k: [VillageRef(**v) for v in values] for k, values in payload["names"].items()}, payload.get("descriptors", []))

    def disambiguate(self, candidates: Iterable[VillageRef], anchors: Iterable[VillageRef]) -> VillageRef | None:
        anchors = [a for a in anchors if a.coord_x is not None and a.coord_y is not None]
        candidates = [c for c in candidates if c.coord_x is not None and c.coord_y is not None]
        if not anchors or not candidates:
            return None
        cx = sum(a.coord_x for a in anchors if a.coord_x is not None) / len(anchors)
        cy = sum(a.coord_y for a in anchors if a.coord_y is not None) / len(anchors)
        ranked = sorted((hypot(c.coord_x-cx, c.coord_y-cy), c) for c in candidates)  # type: ignore[operator]
        if ranked[0][0] > 15000 or (len(ranked) > 1 and ranked[1][0] <= ranked[0][0] * 2):
            return None
        return ranked[0][1]


def build_gazetteer_snapshot(session) -> GazetteerSnapshot:
    """DB adapter kept here deliberately; the snapshot and lookup stay pure."""
    from sqlalchemy import text
    rows = session.execute(text("""
      select v.id,v.ref_name_ar,v.acs_name,v.caza_en,v.coord_x,v.coord_y,
             a.alias_text,a.note
      from villages v left join village_location_aliases a
        on a.village_id=v.id and a.is_active
      where v.is_active and v.caza_en = any(:cazas)
    """), {"cazas": list(ALLOWED_CAZAS)}).mappings()
    names: dict[str, list[VillageRef]] = {}
    for row in rows:
        for name, detail in ((row["ref_name_ar"], None), (row["acs_name"], None), (row["alias_text"], row["note"])):
            if not name:
                continue
            ref = VillageRef(row["id"], row["ref_name_ar"] or row["acs_name"], row["caza_en"], row["coord_x"], row["coord_y"], detail)
            if ref not in names.setdefault(name, []): names[name].append(ref)
    return GazetteerSnapshot(names)
