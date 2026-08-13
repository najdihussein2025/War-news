from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CnrsWebhookPostDTO(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    external_message_id: str
    message_datetime: datetime
    raw_text: str | None = None


CnrsWebhookPayload = CnrsWebhookPostDTO | list[CnrsWebhookPostDTO]
