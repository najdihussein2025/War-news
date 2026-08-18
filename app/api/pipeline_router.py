from fastapi import APIRouter, BackgroundTasks, Depends, Query, status

from app.accounts.models import User
from app.api.deps import require_super_admin
from app.news.services.pipeline_orchestrator import run_full_pipeline_sweep_sync

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


@router.post("/sweep", status_code=status.HTTP_202_ACCEPTED)
def trigger_pipeline_sweep(
    background_tasks: BackgroundTasks,
    limit: int | None = Query(
        default=None,
        ge=1,
        description="Optional cap on eligible rows processed per stage (smoke testing).",
    ),
    _current_user: User = Depends(require_super_admin),
) -> dict[str, str | int]:
    background_tasks.add_task(run_full_pipeline_sweep_sync, max_rows=limit)
    response: dict[str, str | int] = {"status": "scheduled"}
    if limit is not None:
        response["limit"] = limit
    return response
