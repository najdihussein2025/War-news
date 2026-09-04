from pydantic import BaseModel, ConfigDict, Field


class WorkbookImportRowErrorDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    row: int = Field(ge=2)
    error: str


class WorkbookImportSummaryDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    processed: int = Field(ge=0)
    succeeded: int = Field(ge=0)
    skipped: int = Field(default=0, ge=0)
    failed: int = Field(ge=0)
    row_errors: list[WorkbookImportRowErrorDTO]
