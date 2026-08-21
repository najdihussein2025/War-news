from pydantic import BaseModel, ConfigDict


class ConditionOptionDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: int
    action_en: str
    action_ar: str
