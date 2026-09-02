from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.accounts.models import User
from app.api.deps import require_super_admin
from app.core.database import get_db
from app.news.dtos.pipeline_dto import (
    CursorGapResponse,
    LatencyCohortResponse,
    LatencySummaryResponse,
    PipelineHealthResponse,
    StageQueueDepthResponse,
)
from app.news.services.pipeline_health_service import PipelineHealthService
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


@router.get("/health", response_model=PipelineHealthResponse)
def pipeline_health(
    _current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
) -> PipelineHealthResponse:
    """Read-only pipeline health: per-stage queue depth + oldest-waiting age,
    and the live-sweep cursor gap. Super-admin only. Always HTTP 200 - the
    cursor_gap.unhealthy flag is a data field, not a status-code signal."""
    service = PipelineHealthService(db)
    gap = service.cursor_gap()
    latency = service.latency_summary()
    return PipelineHealthResponse(
        stages=[
            StageQueueDepthResponse(
                stage_name=depth.stage_name,
                queue_depth=depth.queue_depth,
                oldest_waiting_seconds=depth.oldest_waiting_seconds,
            )
            for depth in service.stage_queue_depths()
        ],
        cursor_gap=CursorGapResponse(
            sweep_name=gap.sweep_name,
            last_processed_id=gap.last_processed_id,
            max_raw_message_id=gap.max_raw_message_id,
            gap=gap.gap,
            unhealthy=gap.unhealthy,
        ),
        latency=LatencySummaryResponse(
            window_hours=latency.window_hours,
            materialized=LatencyCohortResponse(**vars(latency.materialized)),
            terminal_non_materialized=LatencyCohortResponse(
                **vars(latency.terminal_non_materialized)
            ),
        ),
    )
