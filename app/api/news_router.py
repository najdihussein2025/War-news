from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import require_super_admin
from app.core.database import get_db
from app.news.dtos import (
    AirViolationDTO,
    AirViolationListParams,
    AirViolationListResponse,
)
from app.accounts.models import User
from app.news.repositories import AirViolationRepository
from app.news.services import (
    AirViolationNotFoundError,
    AirViolationService,
    AirViolationWorkbookService,
)

router = APIRouter(prefix="/api/air-violations", tags=["air-violations"])


@router.get("", response_model=AirViolationListResponse)
def list_air_violations(
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    condition_id: int | None = Query(default=None),
    event_date_from: date | None = Query(default=None),
    event_date_to: date | None = Query(default=None),
    caza_en: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_super_admin),
) -> AirViolationListResponse:
    params = AirViolationListParams(
        limit=limit,
        offset=offset,
        condition_id=condition_id,
        event_date_from=event_date_from,
        event_date_to=event_date_to,
        caza_en=caza_en,
    )
    return AirViolationService(AirViolationRepository(db)).list_all(params)


@router.post("/import")
def import_air_violations(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_super_admin),
) -> dict[str, int]:
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Upload an .xlsx workbook.")
    try:
        return AirViolationWorkbookService(db).import_workbook(file.file)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/export")
def export_air_violations(
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_super_admin),
) -> StreamingResponse:
    workbook = AirViolationWorkbookService(db).export_workbook()
    return StreamingResponse(
        workbook,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="air_violations.xlsx"'},
    )


@router.get("/{air_violation_id}", response_model=AirViolationDTO)
def get_air_violation(
    air_violation_id: int,
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_super_admin),
) -> AirViolationDTO:
    try:
        return AirViolationService(AirViolationRepository(db)).get_detail(
            air_violation_id
        )
    except AirViolationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
