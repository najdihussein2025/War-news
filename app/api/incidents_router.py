from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.accounts.models import User
from app.api.deps import require_admin
from app.core.database import get_db
from app.news.dtos import (
    IncidentDetailDTO,
    IncidentListParams,
    IncidentListResponse,
)
from app.news.repositories import IncidentRepository
from app.news.services import IncidentNotFoundError, IncidentService
from app.sources.models import SourceType

router = APIRouter(prefix="/api/incidents", tags=["incidents"])


@router.get("", response_model=IncidentListResponse)
def list_incidents(
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    village: str | None = Query(default=None),
    source_type: SourceType | None = Query(default=None),
    event_date_from: date | None = Query(default=None),
    event_date_to: date | None = Query(default=None),
    flagged_only: bool = Query(default=False),
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_admin),
) -> IncidentListResponse:
    params = IncidentListParams(
        limit=limit,
        offset=offset,
        village=village,
        source_type=source_type.value if source_type is not None else None,
        event_date_from=event_date_from,
        event_date_to=event_date_to,
        flagged_only=flagged_only,
    )
    return IncidentService(IncidentRepository(db)).list_all(params)


@router.get("/{incident_id}", response_model=IncidentDetailDTO)
def get_incident(
    incident_id: UUID,
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_admin),
) -> IncidentDetailDTO:
    try:
        return IncidentService(IncidentRepository(db)).get_detail(incident_id)
    except IncidentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
