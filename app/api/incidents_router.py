from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.accounts.models import User
from app.api.deps import require_admin, require_super_admin
from app.core.database import get_db
from app.news.dtos import (
    IncidentDetailDTO,
    IncidentCreateDTO,
    IncidentDetailsPatchDTO,
    IncidentListParams,
    IncidentListResponse,
    IncidentUpdateDTO,
    WorkbookImportSummaryDTO,
)
from app.news.repositories import IncidentRepository
from app.news.services import IncidentConflictError, IncidentNotFoundError, IncidentService, IncidentWorkbookService
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
    limit: int = Query(default=150, ge=1, le=150),
    offset: int = Query(default=0, ge=0),
    village: str | None = Query(default=None),
    condition: str | None = Query(default=None),
    source_type: SourceType | None = Query(default=None),
    event_date_from: date | None = Query(default=None),
    event_date_to: date | None = Query(default=None),
    flagged_only: bool = Query(default=False),
    verification_status: Literal["matched", "needs_verification"] | None = Query(default=None),
    duplicate_only: bool = Query(default=False),
    sort_order: Literal["newest", "oldest"] = Query(default="newest"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
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
        sort_order=sort_order,
    )
    return IncidentService(IncidentRepository(db)).list_all(params)


@router.post("/import", response_model=WorkbookImportSummaryDTO)
def import_incidents(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
) -> WorkbookImportSummaryDTO:
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload an .xlsx workbook.",
        )

    try:
        return IncidentWorkbookService(db).import_workbook(
            file.file,
            created_by=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.get("/{incident_id}", response_model=IncidentDetailDTO)
def get_incident(
    incident_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
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
    current_user: User = Depends(require_admin),
) -> IncidentDetailDTO:
    try:
        return IncidentService(IncidentRepository(db)).update(incident_id, payload, current_user.id)
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except IncidentConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


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
    except IncidentConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete("/{incident_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_incident(
    incident_id: UUID,
    version: int = Query(ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> None:
    try:
        IncidentService(IncidentRepository(db)).delete(incident_id, version, current_user.id)
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except IncidentConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{incident_id}/edit-lock", response_model=IncidentDetailDTO)
def acquire_incident_edit_lock(
    incident_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> IncidentDetailDTO:
    try:
        return IncidentService(IncidentRepository(db)).acquire_edit_lock(incident_id, current_user.id)
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IncidentConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete("/{incident_id}/edit-lock", status_code=status.HTTP_204_NO_CONTENT)
def release_incident_edit_lock(
    incident_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> None:
    IncidentService(IncidentRepository(db)).release_edit_lock(incident_id, current_user.id)
