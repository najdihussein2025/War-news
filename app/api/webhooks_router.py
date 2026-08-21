from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.sources.actions import ReceiveCnrsWebhookAction
from app.core.database import get_db
from app.news.services.pipeline_jobs import enqueue_pipeline_sweep
from app.news.dtos import AirViolationCreateDTO, AirViolationDTO
from app.news.repositories import AirViolationRepository
from app.news.services import AirViolationService
from app.sources.services.webhook_auth import (
    verify_air_violation_webhook_secret,
    verify_cnrs_webhook_secret,
)
from app.sources.dtos import CnrsWebhookPayload
from app.sources.repositories import SourceRepository

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post(
    "/air-violations",
    response_model=AirViolationDTO,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_air_violation_webhook_secret)],
)
def receive_air_violation(
    payload: AirViolationCreateDTO,
    db: Session = Depends(get_db),
) -> AirViolationDTO:
    """Validate and persist an air violation received from a trusted system."""
    try:
        return AirViolationService(AirViolationRepository(db)).create(payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.post(
    "/cnrs-posts",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_cnrs_webhook_secret)],
)
def receive_cnrs_posts(
    payload: Annotated[CnrsWebhookPayload, Body()],
    source_id: Annotated[int | None, Query(gt=0)] = None,
    db: Session = Depends(get_db),
) -> dict[str, int]:
    sources = SourceRepository(db)
    source = sources.get_by_id(source_id) if source_id is not None else None
    if source is None:
        source = sources.get_active_by_external_id("cnrs_webhook")
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Active CNRS webhook source is not configured.",
        )

    action = ReceiveCnrsWebhookAction(sources=sources)
    result = action.execute(payload=payload, source_id=source.id)
    if db is not None:
        enqueue_pipeline_sweep(db, use_advisory_lock=False)
    return result
