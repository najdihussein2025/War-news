"""Compare the project ACS village file with the GeoNames Lebanon gazetteer.

GeoNames is a second-source gazetteer, not an official definition of a village.
The output therefore contains *candidates* for human review, not rows that should
be inserted into Villages.json automatically.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import unicodedata
import zipfile
from difflib import SequenceMatcher
from pathlib import Path


POPULATED_CODES = {
    "PPL", "PPLA", "PPLA2", "PPLA3", "PPLA4", "PPLC", "PPLF", "PPLG",
    "PPLL", "PPLQ", "PPLR", "PPLS", "PPLW",
}


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[إأآٱ]", "ا", value)
    value = value.replace("ة", "ه").replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي")
    value = re.sub(r"\b(?:al|el|et|ed|ad)[\s-]+", "", value)
    return "".join(ch for ch in value if ch.isalnum())


def utm36n_to_wgs84(easting: float, northing: float) -> tuple[float, float]:
    # Standard inverse UTM calculation for WGS84, zone 36 north.
    a, ecc2, k0 = 6378137.0, 0.00669438, 0.9996
    e1 = (1 - math.sqrt(1 - ecc2)) / (1 + math.sqrt(1 - ecc2))
    x, y = easting - 500000.0, northing
    m = y / k0
    mu = m / (a * (1 - ecc2 / 4 - 3 * ecc2**2 / 64 - 5 * ecc2**3 / 256))
    phi1 = mu + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu)
    phi1 += (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu)
    phi1 += 151 * e1**3 / 96 * math.sin(6 * mu) + 1097 * e1**4 / 512 * math.sin(8 * mu)
    ep2 = ecc2 / (1 - ecc2)
    n1 = a / math.sqrt(1 - ecc2 * math.sin(phi1) ** 2)
    t1, c1, r1 = math.tan(phi1) ** 2, ep2 * math.cos(phi1) ** 2, a * (1 - ecc2) / (1 - ecc2 * math.sin(phi1) ** 2) ** 1.5
    d = x / (n1 * k0)
    lat = phi1 - (n1 * math.tan(phi1) / r1) * (
        d**2 / 2 - (5 + 3*t1 + 10*c1 - 4*c1**2 - 9*ep2) * d**4 / 24
        + (61 + 90*t1 + 298*c1 + 45*t1**2 - 252*ep2 - 3*c1**2) * d**6 / 720
    )
    lon = math.radians(33) + (
        d - (1 + 2*t1 + c1) * d**3 / 6
        + (5 - 2*c1 + 28*t1 - 3*c1**2 + 8*ep2 + 24*t1**2) * d**5 / 120
    ) / math.cos(phi1)
    return math.degrees(lat), math.degrees(lon)


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371.0088 * 2 * math.asin(math.sqrt(h))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--villages", type=Path, default=Path("Data/Villages.json"))
    parser.add_argument("--geonames", type=Path, default=Path("Data/LB_geonames.zip"))
    parser.add_argument("--output", type=Path, default=Path("Data/missing_village_candidates.csv"))
    args = parser.parse_args()

    villages = json.loads(args.villages.read_text(encoding="utf-8-sig"))
    known_names: dict[str, list[int]] = {}
    known_points: list[tuple[float, float, int]] = []
    for i, village in enumerate(villages):
        for field in ("acs_name", "cad_name", "ref_name_en", "ref_name_ar"):
            key = normalize(str(village.get(field) or ""))
            if key:
                known_names.setdefault(key, []).append(i)
        if village.get("coord_x") is not None and village.get("coord_y") is not None:
            known_points.append((*utm36n_to_wgs84(float(village["coord_x"]), float(village["coord_y"])), i))

    with zipfile.ZipFile(args.geonames) as archive:
        lines = archive.read("LB.txt").decode("utf-8").splitlines()

    candidates: list[dict[str, object]] = []
    matched = 0
    for line in lines:
        fields = line.split("\t")
        if len(fields) < 19 or fields[6] != "P" or fields[7] not in POPULATED_CODES:
            continue
        geoid, name, ascii_name, aliases = fields[:4]
        lat, lon, code, population = float(fields[4]), float(fields[5]), fields[7], int(fields[14] or 0)
        source_names = [name, ascii_name, *aliases.split(",")]
        keys = {normalize(n) for n in source_names if normalize(n)}
        exact_indices = {i for key in keys for i in known_names.get(key, [])}
        nearest_dist, nearest_i = min(
            ((distance_km((lat, lon), (klat, klon)), i) for klat, klon, i in known_points),
            default=(9999.0, -1),
        )
        if exact_indices or nearest_dist <= 0.75:
            matched += 1
            continue
        nearest = villages[nearest_i] if nearest_i >= 0 else {}
        nearest_keys = [normalize(str(nearest.get(f) or "")) for f in ("acs_name", "cad_name", "ref_name_en")]
        fuzzy = max((SequenceMatcher(None, a, b).ratio() for a in keys for b in nearest_keys if b), default=0.0)
        confidence = "high" if nearest_dist >= 5 and fuzzy < 0.72 else "medium" if nearest_dist >= 2 and fuzzy < 0.82 else "low"
        candidates.append({
            "review_confidence": confidence,
            "geonames_id": geoid,
            "name": name,
            "ascii_name": ascii_name,
            "feature_code": code,
            "population": population,
            "latitude": lat,
            "longitude": lon,
            "nearest_json_name": nearest.get("ref_name_en", ""),
            "nearest_json_acs_code": nearest.get("acs_code", ""),
            "distance_km": round(nearest_dist, 3),
            "name_similarity": round(fuzzy, 3),
            "geonames_url": f"https://www.geonames.org/{geoid}",
        })

    candidates.sort(key=lambda row: ({"high": 0, "medium": 1, "low": 2}[str(row["review_confidence"])], -int(row["population"]), str(row["name"])))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(candidates[0]) if candidates else [])
        if candidates:
            writer.writeheader()
            writer.writerows(candidates)
    counts = {level: sum(row["review_confidence"] == level for row in candidates) for level in ("high", "medium", "low")}
    print(json.dumps({"json_records": len(villages), "geonames_matched": matched, "candidates": len(candidates), "confidence": counts, "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
