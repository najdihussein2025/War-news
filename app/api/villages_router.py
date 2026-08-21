from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.accounts.models import User
from app.api.deps import require_admin
from app.core.database import get_db
from app.news.dtos import VillageOptionDTO
from app.news.repositories.village_repository import VillageRepository

router = APIRouter(prefix="/api/villages", tags=["villages"])


@router.get("", response_model=list[VillageOptionDTO])
def list_villages(
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_admin),
) -> list[VillageOptionDTO]:
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
            )
        )
    return items
