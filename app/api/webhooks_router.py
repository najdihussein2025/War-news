from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.sources.actions import ReceiveCnrsWebhookAction
from app.core.database import get_db
from app.news.services.pipeline_orchestrator import run_full_pipeline_sweep_sync
from app.sources.services.webhook_auth import verify_cnrs_webhook_secret
from app.sources.dtos import CnrsWebhookPayload
from app.sources.repositories import SourceRepository

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


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
    background_tasks.add_task(run_full_pipeline_sweep_sync)
    return result
