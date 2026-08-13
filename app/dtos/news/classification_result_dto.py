from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ClassificationVerdict(str, Enum):
    relevant = "relevant"
    not_relevant = "not_relevant"
    uncertain = "uncertain"


class ClassificationResultDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    raw_message_id: int
    verdict: ClassificationVerdict
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    reasoning: str | None = None
    backend: str
    raw_response: dict[str, Any] | None = None
