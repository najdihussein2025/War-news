import math
from datetime import date, datetime, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.news.dtos.map_event_dto import MapEventDTO, MapEventResponseDTO
from app.news.models import AirViolation, Condition, Incident, RawMessage, Village
from app.sources.models import Source


def utm36n_to_wgs84(easting: float, northing: float) -> tuple[float, float]:
    """Convert the ACS village coordinates from UTM zone 36N to WGS84."""
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
    t1 = math.tan(phi1) ** 2
    c1 = ep2 * math.cos(phi1) ** 2
    r1 = a * (1 - ecc2) / (1 - ecc2 * math.sin(phi1) ** 2) ** 1.5
    d = x / (n1 * k0)
    lat = phi1 - (n1 * math.tan(phi1) / r1) * (
        d**2 / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1**2 - 9 * ep2) * d**4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1**2 - 252 * ep2 - 3 * c1**2) * d**6 / 720
    )
    lon = math.radians(33) + (
        d
        - (1 + 2 * t1 + c1) * d**3 / 6
        + (5 - 2 * c1 + 28 * t1 - 3 * c1**2 + 8 * ep2 + 24 * t1**2) * d**5 / 120
    ) / math.cos(phi1)
    return math.degrees(lat), math.degrees(lon)


def _occurred_at(event_date: date, event_time: time | None) -> datetime:
    return datetime.combine(event_date, event_time or time.min)


def _matched_village_id(match_result: dict | None) -> int | None:
    result = match_result or {}
    matches = result.get("village_matches") or []
    value = matches[0].get("matched_village_id") if matches else result.get("matched_village_id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class MapEventRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_events(
        self,
        *,
        event_date_from: date | None,
        event_date_to: date | None,
        event_types: set[str],
        limit: int,
    ) -> MapEventResponseDTO:
        villages = list(self.db.scalars(select(Village).where(
            Village.coord_x.is_not(None), Village.coord_y.is_not(None)
        )))
        village_by_id = {v.id: v for v in villages}
        caza_points: dict[str, list[Village]] = {}
        for village in villages:
            if village.caza_en:
                caza_points.setdefault(village.caza_en.casefold(), []).append(village)

        items: list[MapEventDTO] = []
        unmapped_count = 0
        fetch_limit = limit + 1

        if "incident" in event_types:
            query = (
                select(Incident, Village, Condition, Source)
                .outerjoin(Village, Village.id == Incident.village_id)
                .outerjoin(Condition, Condition.id == Incident.condition_id)
                .outerjoin(Source, Source.id == Incident.source_id)
                .where(Incident.is_deleted.is_(False))
            )
            if event_date_from:
                query = query.where(Incident.event_date >= event_date_from)
            if event_date_to:
                query = query.where(Incident.event_date <= event_date_to)
            for incident, village, condition, source in self.db.execute(
                query.order_by(Incident.event_date.desc(), Incident.event_time.desc().nullslast()).limit(fetch_limit)
            ):
                if not village or village.coord_x is None or village.coord_y is None:
                    unmapped_count += 1
                    continue
                latitude, longitude = utm36n_to_wgs84(village.coord_x, village.coord_y)
                category = condition.action_en if condition and condition.action_en else "Incident"
                items.append(MapEventDTO(
                    id=str(incident.id), event_type="incident", category=category,
                    title=category, summary=incident.khabar,
                    occurred_at=_occurred_at(incident.event_date, incident.event_time),
                    latitude=latitude, longitude=longitude,
                    village=village.ref_name_en or village.acs_name or village.cad_name,
                    caza=village.caza_en, source=source.name if source else None,
                    detail_path=f"incidents/{incident.id}",
                ))

        if "air_violation" in event_types:
            query = (
                select(AirViolation, RawMessage.match_result, Condition, Source)
                .outerjoin(RawMessage, RawMessage.id == AirViolation.raw_message_id)
                .join(Condition, Condition.id == AirViolation.condition_id)
                .join(Source, Source.id == AirViolation.source_id)
            )
            if event_date_from:
                query = query.where(AirViolation.event_date >= event_date_from)
            if event_date_to:
                query = query.where(AirViolation.event_date <= event_date_to)
            for violation, match_result, condition, source in self.db.execute(
                query.order_by(AirViolation.event_date.desc(), AirViolation.event_time.desc().nullslast()).limit(fetch_limit)
            ):
                village = village_by_id.get(_matched_village_id(match_result))
                if (
                    village
                    and violation.caza_en
                    and village.caza_en
                    and village.caza_en.casefold() != violation.caza_en.casefold()
                ):
                    # Ambiguous names such as "Kafr" can resolve to a village in
                    # the wrong district. Prefer the recorded caza centroid over
                    # placing the event at a contradictory precise location.
                    village = None
                points = caza_points.get((violation.caza_en or "").casefold(), [])
                if village and village.coord_x is not None and village.coord_y is not None:
                    latitude, longitude = utm36n_to_wgs84(village.coord_x, village.coord_y)
                    village_name = village.ref_name_en or village.acs_name or village.cad_name
                elif points:
                    converted = [utm36n_to_wgs84(v.coord_x, v.coord_y) for v in points if v.coord_x is not None and v.coord_y is not None]
                    latitude = sum(point[0] for point in converted) / len(converted)
                    longitude = sum(point[1] for point in converted) / len(converted)
                    village_name = None
                else:
                    unmapped_count += 1
                    continue
                category = condition.action_en or "Air violation"
                items.append(MapEventDTO(
                    id=str(violation.id), event_type="air_violation", category=category,
                    title=category, summary=violation.khabar,
                    occurred_at=_occurred_at(violation.event_date, violation.event_time),
                    latitude=latitude, longitude=longitude, village=village_name,
                    caza=violation.caza_en, source=source.name, detail_path="air-violations",
                ))

        items.sort(key=lambda item: item.occurred_at, reverse=True)
        truncated = len(items) > limit
        return MapEventResponseDTO(items=items[:limit], unmapped_count=unmapped_count, truncated=truncated)
