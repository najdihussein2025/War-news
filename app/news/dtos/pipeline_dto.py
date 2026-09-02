from pydantic import BaseModel, ConfigDict, Field


class StageSweepResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    stage: str
    processed: int
    succeeded: int
    failed: int
    aborted: bool = False
    abort_reason: str | None = None
    unprocessed: int = 0
    elapsed_seconds: float = Field(ge=0.0)


class PipelineSweepResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    skipped: bool = False
    skip_reason: str | None = None
    stages: list[StageSweepResult] = Field(default_factory=list)
    elapsed_seconds: float = Field(default=0.0, ge=0.0)
    partial_failure: bool = False


class StageQueueDepthResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    stage_name: str
    queue_depth: int
    oldest_waiting_seconds: float | None = None
