from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.sources.actions import ReceiveCnrsWebhookAction
from app.core.database import get_db
from app.news.services.pipeline.pipeline_jobs import (
    drain_one_enqueued_pipeline_sweep_job,
    enqueue_pipeline_sweep,
)
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


def _drain_one_enqueued_pipeline_job() -> None:
    drain_one_enqueued_pipeline_sweep_job()


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
    background_tasks: BackgroundTasks,
    source_id: Annotated[int | None, Query(gt=0)] = None,
    db: Session = Depends(get_db),
) -> dict[str, int]:
    sources = SourceRepository(db)
    source = sources.get_active_by_external_id("cnrs_webhook")
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Active CNRS webhook source is not configured.",
        )

    action = ReceiveCnrsWebhookAction(sources=sources)
    result = action.execute(payload=payload, source_id=source.id)
    if db is not None and result.get("saved", 0) > 0:
        enqueue_pipeline_sweep(db, use_advisory_lock=False)
        background_tasks.add_task(_drain_one_enqueued_pipeline_job)
    return result
