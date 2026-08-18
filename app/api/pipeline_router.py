from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.accounts.models import User
from app.api.deps import require_super_admin
from app.core.database import get_db
from app.news.services.pipeline_jobs import enqueue_pipeline_sweep

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


@router.post("/sweep", status_code=status.HTTP_202_ACCEPTED)
def trigger_pipeline_sweep(
    limit: int | None = Query(
        default=None,
        ge=1,
        description="Optional cap on eligible rows processed per stage (smoke testing).",
    ),
    _current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
) -> dict[str, str | int]:
    job_id = enqueue_pipeline_sweep(
        db,
        max_rows=limit,
        use_advisory_lock=True,
    )
    response: dict[str, str | int] = {
        "status": "queued",
        "job_id": job_id,
    }
    if limit is not None:
        response["limit"] = limit
    return response
