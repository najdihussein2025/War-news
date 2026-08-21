from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class IngestSourceData(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_id: int
    page_limit: int = Field(default=500, ge=1)
    max_batches: int | None = Field(default=None, ge=1)
    min_message_datetime: datetime | None = None


class IngestionSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    fetched: int
    inserted: int
    skipped_duplicate: int
    skipped_before_cutoff: int
    skipped_blocked: int
    failed: int
    final_cursor: str | None
