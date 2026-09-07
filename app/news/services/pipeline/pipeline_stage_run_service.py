from datetime import datetime, timedelta, timezone

from app.core.database import SessionLocal
from app.news.dtos.pipeline_dto import StageSweepResult
from app.news.models.pipeline_stage_run import PipelineStageRun


def record_stage_run(result: StageSweepResult, *, sweep_type: str) -> None:
    """Persist completed stage telemetry in a short transaction after stage work."""
    finished_at = datetime.now(timezone.utc)
    with SessionLocal() as db:
        db.add(PipelineStageRun(
            stage_name=result.stage,
            sweep_type=sweep_type,
            started_at=finished_at - timedelta(seconds=result.elapsed_seconds),
            finished_at=finished_at,
            rows_claimed=result.processed,
            rows_succeeded=result.succeeded,
            rows_failed=result.failed,
            error_summary=result.abort_reason,
            aborted=result.aborted,
        ))
        db.commit()
