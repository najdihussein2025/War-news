from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.accounts.models import User
from app.api.deps import require_admin
from app.core.database import get_db
from app.news.dtos import (
    IncidentDetailDTO,
    IncidentCreateDTO,
    IncidentDetailsPatchDTO,
    IncidentListParams,
    IncidentListResponse,
    IncidentUpdateDTO,
)
from app.news.repositories import IncidentRepository
from app.news.services import IncidentNotFoundError, IncidentService
from app.sources.models import SourceType

router = APIRouter(prefix="/api/incidents", tags=["incidents"])


@router.post("", response_model=IncidentDetailDTO, status_code=status.HTTP_201_CREATED)
def create_incident(
    payload: IncidentCreateDTO,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> IncidentDetailDTO:
    try:
        return IncidentService(IncidentRepository(db)).create(payload, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("", response_model=IncidentListResponse)
def list_incidents(
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    village: str | None = Query(default=None),
    condition: str | None = Query(default=None),
    source_type: SourceType | None = Query(default=None),
    event_date_from: date | None = Query(default=None),
    event_date_to: date | None = Query(default=None),
    flagged_only: bool = Query(default=False),
    verification_status: Literal["matched", "needs_verification"] | None = Query(default=None),
    duplicate_only: bool = Query(default=False),
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_admin),
) -> IncidentListResponse:
    params = IncidentListParams(
        limit=limit,
        offset=offset,
        village=village,
        condition=condition,
        source_type=source_type.value if source_type is not None else None,
        event_date_from=event_date_from,
        event_date_to=event_date_to,
        flagged_only=flagged_only,
        verification_status=verification_status,
        duplicate_only=duplicate_only,
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


@router.put("/{incident_id}", response_model=IncidentDetailDTO)
def update_incident(
    incident_id: UUID,
    payload: IncidentUpdateDTO,
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_admin),
) -> IncidentDetailDTO:
    try:
        return IncidentService(IncidentRepository(db)).update(incident_id, payload)
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/{incident_id}/details", response_model=IncidentDetailDTO)
def update_incident_details(
    incident_id: UUID,
    payload: IncidentDetailsPatchDTO,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> IncidentDetailDTO:
    try:
        return IncidentService(IncidentRepository(db)).update_details(
            incident_id,
            payload,
            current_user.id,
        )
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.delete("/{incident_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_incident(
    incident_id: UUID,
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_admin),
) -> None:
    try:
        IncidentService(IncidentRepository(db)).delete(incident_id)
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
