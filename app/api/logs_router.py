from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.accounts.models import User
from app.api.deps import require_admin
from app.core.database import get_db
from app.logs.actions import ListIngestionLogsAction, ListLoginLogsAction
from app.logs.dtos import AuditLogFilterData, AuditLogPageDTO, IngestionLogFilterData, IngestionLogItemDTO, IngestionLogPageDTO, LoginLogFilterData, LoginLogPageDTO
from app.logs.repositories import AuditLogRepository, IngestionLogRepository, LoginLogRepository
from app.logs.services import run_ingestion_retry

router = APIRouter(prefix="/api/logs", tags=["logs"])

@router.get("/audit", response_model=AuditLogPageDTO)
def list_audit_logs(search: str | None = None, action: str | None = None, date_from: date | None = None, date_to: date | None = None, page: int = Query(default=1, ge=1), page_size: int = Query(default=100, ge=1, le=100), db: Session = Depends(get_db), _current_user: User = Depends(require_admin)) -> AuditLogPageDTO:
    return AuditLogRepository(db).list_page(AuditLogFilterData(search=search, action=action, date_from=date_from, date_to=date_to, page=page, page_size=page_size))


@router.get("/login", response_model=LoginLogPageDTO)
def list_login_logs(
    search: str | None = None,
    result: Literal["success", "failure", "all"] = "success",
    date_from: date | None = None,
    date_to: date | None = None,
    created_after: datetime | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_admin),
) -> LoginLogPageDTO:
    return ListLoginLogsAction(LoginLogRepository(db)).execute(
        LoginLogFilterData(
            search=search,
            success=None if result == "all" else result == "success",
            date_from=date_from,
            date_to=date_to,
            created_after=created_after,
            page=page,
            page_size=page_size,
        )
    )


@router.get("/ingestion", response_model=IngestionLogPageDTO)
def list_ingestion_logs(
    source_id: int | None = None,
    run_status: str | None = Query(default=None, alias="status"),
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=100),
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_admin),
) -> IngestionLogPageDTO:
    return ListIngestionLogsAction(IngestionLogRepository(db)).execute(
        IngestionLogFilterData(source_id=source_id, status=run_status, date_from=date_from, date_to=date_to, page=page, page_size=page_size)
    )


@router.get("/ingestion/{log_id}", response_model=IngestionLogItemDTO)
def get_ingestion_log(
    log_id: int,
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_admin),
) -> IngestionLogItemDTO:
    row = IngestionLogRepository(db).get(log_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ingestion log was not found.")
    return row


@router.post("/ingestion/{log_id}/retry", response_model=IngestionLogItemDTO, status_code=status.HTTP_202_ACCEPTED)
def retry_ingestion(
    log_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_admin),
) -> IngestionLogItemDTO:
    retry = IngestionLogRepository(db).start_retry(log_id)
    if retry is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only an existing failed ingestion run can be retried.")
    background_tasks.add_task(run_ingestion_retry, retry.source_id, retry.id)
    return retry
