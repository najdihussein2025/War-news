from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.accounts.models import User
from app.api.deps import require_admin
from app.core.database import get_db
from app.news.dtos.map_event_dto import MapEventResponseDTO
from app.news.repositories.map_event_repository import MapEventRepository

router = APIRouter(prefix="/api/map", tags=["map"])


@router.get("/events", response_model=MapEventResponseDTO)
def list_map_events(
    event_date_from: date | None = None,
    event_date_to: date | None = None,
    event_type: list[str] = Query(default=["incident", "air_violation"]),
    limit: int = Query(default=2000, ge=1, le=5000),
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_admin),
) -> MapEventResponseDTO:
    allowed_types = {value for value in event_type if value in {"incident", "air_violation"}}
    return MapEventRepository(db).list_events(
        event_date_from=event_date_from,
        event_date_to=event_date_to,
        event_types=allowed_types,
        limit=limit,
    )
