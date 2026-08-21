from pydantic import BaseModel, ConfigDict


class VillageOptionDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    value: str
    label: str
    ref_name_en: str | None = None
    ref_name_ar: str | None = None
