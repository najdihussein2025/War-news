from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CnrsWebhookPostDTO(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    external_message_id: str
    message_datetime: datetime
    raw_text: str | None = None
    source_platform: str | None = None
    source_name: str = Field(min_length=1)
    origin_account: str | None = None


CnrsWebhookPayload = CnrsWebhookPostDTO | list[CnrsWebhookPostDTO]
