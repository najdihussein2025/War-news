from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.accounts.models import User
from app.api.deps import require_admin
from app.core.cache import delete_keys, get_json, set_json
from app.core.database import get_db
from app.news.dtos import VillageOptionDTO
from app.news.repositories.village_repository import VillageRepository

router = APIRouter(prefix="/api/villages", tags=["villages"])

VILLAGES_CACHE_KEY = "reference:villages:v1"
VILLAGES_CACHE_TTL_SECONDS = 60 * 60


@router.get("", response_model=list[VillageOptionDTO])
def list_villages(
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_admin),
) -> list[VillageOptionDTO]:
    cached = get_json(VILLAGES_CACHE_KEY)
    if isinstance(cached, list):
        try:
            return [VillageOptionDTO.model_validate(item) for item in cached]
        except (TypeError, ValueError):
            delete_keys(VILLAGES_CACHE_KEY)

    villages = VillageRepository(db).list_active()
    items: list[VillageOptionDTO] = []
    for village in villages:
        value = (
            (village.ref_name_en or "").strip()
            or (village.cad_name or "").strip()
            or (village.acs_name or "").strip()
            or (village.ref_name_ar or "").strip()
        )
        if not value:
            continue
        english = (village.ref_name_en or village.cad_name or village.acs_name or "").strip()
        arabic = (village.ref_name_ar or "").strip()
        if english and arabic:
            label = f"{english} - {arabic}"
        else:
            label = english or arabic
        items.append(
            VillageOptionDTO(
                id=village.id,
                value=value,
                label=label,
                ref_name_en=village.ref_name_en,
                ref_name_ar=village.ref_name_ar,
                caza_en=village.caza_en,
                caza_ar=village.caza_ar,
            )
        )
    set_json(
        VILLAGES_CACHE_KEY,
        [item.model_dump(mode="json") for item in items],
        VILLAGES_CACHE_TTL_SECONDS,
    )
    return items
