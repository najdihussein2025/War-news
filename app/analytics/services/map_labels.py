"""Filter-independent village label geometry from the villages table, cached once."""
import math

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.analytics.services.analytics_service import cached
from app.news.repositories.map_event_repository import utm36n_to_wgs84


def village_labels(db: Session) -> dict:
    def build():
        rows = db.execute(text("""
            SELECT admin_area_code AS code, ref_name_en, ref_name_ar, coord_x, coord_y
            FROM villages WHERE is_active IS TRUE ORDER BY id
        """)).mappings()
        features, missing, unlinked = [], 0, 0
        for row in rows:
            if row["coord_x"] is None or row["coord_y"] is None:
                missing += 1
                continue
            lat, lon = utm36n_to_wgs84(row["coord_x"], row["coord_y"])
            if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
                missing += 1
                continue
            if not row["code"]:
                unlinked += 1
                continue
            features.append({
                "type": "Feature", "id": row["code"],
                "properties": {"code": row["code"], "name_en": row["ref_name_en"] or "",
                               "name_ar": row["ref_name_ar"] or ""},
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
            })
        return {"type": "FeatureCollection", "features": features,
                "missing_coordinates": missing, "unlinked": unlinked}

    return cached("village-labels-v1", {}, build)
