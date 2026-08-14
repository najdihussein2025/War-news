from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query, status
from sqlalchemy.orm import Session

from app.sources.actions import ReceiveCnrsWebhookAction
from app.core.database import get_db
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
    source_id: Annotated[int, Query(gt=0)],
    db: Session = Depends(get_db),
) -> dict[str, int]:
    action = ReceiveCnrsWebhookAction(sources=SourceRepository(db))
    return action.execute(payload=payload, source_id=source_id)
