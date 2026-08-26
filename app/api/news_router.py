from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import require_admin, require_super_admin
from app.core.cache import get_cache_version, get_json, increment, set_json
from app.core.database import get_db
from app.news.dtos import (
    AirViolationCreateDTO,
    AirViolationDTO,
    AirViolationListParams,
    AirViolationListResponse,
    AirViolationSummaryDTO,
    WorkbookImportSummaryDTO,
)
from app.accounts.models import User
from app.news.repositories import AirViolationRepository
from app.news.services import (
    AirViolationNotFoundError,
    AirViolationService,
    AirViolationWorkbookService,
)

router = APIRouter(prefix="/api/air-violations", tags=["air-violations"])
AIR_VIOLATION_CACHE_VERSION_KEY = "air-violations:cache-version"


@router.post("", response_model=AirViolationDTO, status_code=status.HTTP_201_CREATED)
def create_air_violation(
    payload: AirViolationCreateDTO,
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_admin),
) -> AirViolationDTO:
    try:
        result = AirViolationService(AirViolationRepository(db)).create(payload)
        return result
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.put("/{air_violation_id}", response_model=AirViolationDTO)
def update_air_violation(
    air_violation_id: int,
    payload: AirViolationCreateDTO,
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_admin),
) -> AirViolationDTO:
    try:
        result = AirViolationService(AirViolationRepository(db)).update(
            air_violation_id,
            payload,
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AirViolationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{air_violation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_air_violation(
    air_violation_id: int,
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_admin),
) -> None:
    try:
        AirViolationService(AirViolationRepository(db)).delete(air_violation_id)
    except AirViolationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("", response_model=AirViolationListResponse)
def list_air_violations(
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    condition_id: int | None = Query(default=None),
    event_date_from: date | None = Query(default=None),
    event_date_to: date | None = Query(default=None),
    caza_en: str | None = Query(default=None),
    last_hours: int | None = Query(default=None, ge=1, le=8760),
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_admin),
) -> AirViolationListResponse:
    params = AirViolationListParams(
        limit=limit,
        offset=offset,
        condition_id=condition_id,
        event_date_from=event_date_from,
        event_date_to=event_date_to,
        caza_en=caza_en,
        last_hours=last_hours,
    )
    return AirViolationService(AirViolationRepository(db)).list_all(params)


@router.get("/summary", response_model=AirViolationSummaryDTO)
def summarize_air_violations(
    event_date_from: date | None = Query(default=None),
    event_date_to: date | None = Query(default=None),
    caza_en: str | None = Query(default=None),
    last_hours: int | None = Query(default=None, ge=1, le=8760),
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_admin),
) -> AirViolationSummaryDTO:
    version = get_cache_version(AIR_VIOLATION_CACHE_VERSION_KEY)
    normalized_caza = caza_en.strip().casefold() if caza_en else "all"
    key = (
        f"air-violations:summary:v{version}:caza={normalized_caza}:"
        f"from={event_date_from or 'none'}:to={event_date_to or 'none'}:"
        f"hours={last_hours or 'none'}"
    )
    cached = get_json(key)
    if isinstance(cached, dict):
        try:
            return AirViolationSummaryDTO.model_validate(cached)
        except (TypeError, ValueError):
            pass

    params = AirViolationListParams(
        limit=1,
        offset=0,
        event_date_from=event_date_from,
        event_date_to=event_date_to,
        caza_en=caza_en,
        last_hours=last_hours,
    )
    result = AirViolationService(AirViolationRepository(db)).get_summary(params)
    set_json(key, result.model_dump(mode="json"), 15)
    return result


@router.post("/import", response_model=WorkbookImportSummaryDTO)
def import_air_violations(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_super_admin),
) -> WorkbookImportSummaryDTO:
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Upload an .xlsx workbook.")
    try:
        result = AirViolationWorkbookService(db).import_workbook(file.file)
        if result.succeeded:
            increment(AIR_VIOLATION_CACHE_VERSION_KEY)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/export")
def export_air_violations(
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_admin),
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
    _current_user: User = Depends(require_admin),
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
