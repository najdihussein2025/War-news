from datetime import date, datetime, timezone
from typing import Literal
from uuid import UUID

import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.accounts.models import User
from app.api.deps import require_admin, require_super_admin
from app.core.database import get_db
from app.news.dtos import (
    IncidentDetailDTO,
    IncidentDuplicateCandidateDTO,
    IncidentDuplicateResolutionDTO,
    IncidentDuplicateResolutionResultDTO,
    IncidentCreateDTO,
    IncidentDetailsPatchDTO,
    INCIDENTS_START_DATE,
    IncidentListParams,
    IncidentListResponse,
    IncidentUpdateDTO,
    IncidentVerificationDTO,
    WorkbookImportSummaryDTO,
)
from app.news.repositories import IncidentRepository
from app.news.models import Incident, IncidentOrigin
from app.news.services.incidents.soft_delete import soft_delete_incident
from app.news.services.summaries.decision_reasons import append_note, note
from sqlalchemy import select
from app.news.services import IncidentConflictError, IncidentNotFoundError, IncidentService, IncidentWorkbookService
from app.news.services.realtime.incident_event_stream import incident_event_stream
from app.news.services.incidents.imported_incident_enrichment import enrich_imported_incidents
from app.sources.models import SourceType

router = APIRouter(prefix="/api/incidents", tags=["incidents"])


@router.get("/{incident_id}/verification-flags")
def get_incident_verification_flags(
    incident_id: UUID,
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_admin),
) -> list[dict]:
    from app.news.repositories.incident_verification_flag_repository import IncidentVerificationFlagRepository

    return [
        {
            "id": flag.id,
            "reason_code": flag.reason_code,
            "severity": flag.severity,
            "summary": (flag.detail or {}).get("summary"),
            "created_at": flag.created_at,
        }
        for flag in IncidentVerificationFlagRepository(db).list_open_for_incident(incident_id)
    ]


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
    cursor: str | None = Query(default=None),
    village: str | None = Query(default=None),
    condition: str | None = Query(default=None),
    source_type: SourceType | None = Query(default=None),
    source_name: str | None = Query(default=None),
    event_date_from: date | None = Query(default=INCIDENTS_START_DATE),
    event_date_to: date | None = Query(default=None),
    flagged_only: bool = Query(default=False),
    verification_status: Literal["auto_processed", "needs_verification", "verified", "rejected"] | None = Query(default=None),
    verification_type: Literal["duplicate", "casualty_missing_number", "casualty_aggregate_toll"] | None = Query(default=None),
    duplicate_only: bool = Query(default=False),
    has_casualties: bool = Query(default=False),
    sort_order: Literal["newest", "oldest"] = Query(default="newest"),
    group_by: Literal["raw_message"] | None = Query(default=None),
    summary_added: bool = Query(default=False),
    decision_reason: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> IncidentListResponse:
    params = IncidentListParams(
        limit=limit,
        cursor=cursor,
        village=village,
        condition=condition,
        source_type=source_type.value if source_type is not None else None,
        source_name=source_name,
        event_date_from=event_date_from,
        event_date_to=event_date_to,
        flagged_only=flagged_only,
        verification_status=verification_status,
        verification_type=verification_type,
        duplicate_only=duplicate_only,
        has_casualties=has_casualties,
        sort_order=sort_order,
        group_by=group_by,
        summary_added=summary_added,
        decision_reason=decision_reason,
    )
    return IncidentService(IncidentRepository(db)).list_all(params)


@router.get("/stream")
async def stream_incidents(
    request: Request,
    current_user: User = Depends(require_admin),
) -> StreamingResponse:
    queue = await incident_event_stream.subscribe()

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            await incident_event_stream.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{incident_id}/verification", response_model=IncidentDetailDTO)
def verify_incident(
    incident_id: UUID,
    payload: IncidentVerificationDTO,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> IncidentDetailDTO:
    try:
        return IncidentService(IncidentRepository(db)).set_verification(incident_id, payload, current_user.id)
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except IncidentConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/import", response_model=WorkbookImportSummaryDTO)
def import_incidents(
    background_tasks: BackgroundTasks,
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
        workbook_service = IncidentWorkbookService(db)
        summary = workbook_service.import_workbook(
            file.file,
            created_by=current_user.id,
        )
        queued_ids = list(
            getattr(workbook_service, "queued_raw_message_ids", [])
        )
        if queued_ids:
            background_tasks.add_task(enrich_imported_incidents, queued_ids)
        return summary
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


@router.get(
    "/{incident_id}/duplicate-candidate",
    response_model=IncidentDuplicateCandidateDTO,
)
def get_incident_duplicate_candidate(
    incident_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> IncidentDuplicateCandidateDTO:
    try:
        return IncidentService(IncidentRepository(db)).get_duplicate_candidate(incident_id)
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/{incident_id}/duplicate-resolution",
    response_model=IncidentDuplicateResolutionResultDTO,
)
def resolve_incident_duplicate(
    incident_id: UUID,
    payload: IncidentDuplicateResolutionDTO,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> IncidentDuplicateResolutionResultDTO:
    try:
        return IncidentService(IncidentRepository(db)).resolve_duplicate(
            incident_id, payload, current_user.id
        )
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except IncidentConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


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


@router.post("/{incident_id}/reject-summary", status_code=status.HTTP_204_NO_CONTENT)
def reject_summary_incident(
    incident_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> None:
    """Reject a summary-created row without reusing the generic delete reason."""
    incident = db.scalar(select(Incident).where(Incident.id == incident_id, Incident.is_deleted.is_(False)).with_for_update())
    if incident is None or incident.origin != IncidentOrigin.summary:
        raise HTTPException(status_code=404, detail="Active summary incident not found.")
    now = date.today().isoformat()
    incident.decision_reason = "REJECTED_BY_ADMIN"
    incident.decided_at = datetime.now(timezone.utc)
    incident.note = append_note(incident.note, note("REJECTED_BY_ADMIN", user=current_user.email, decided_date=now))
    soft_delete_incident(db, incident, reason="REJECTED_BY_ADMIN", performed_by=current_user.id)
    db.commit()


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
