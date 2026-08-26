from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.accounts.models import User
from app.api.deps import require_admin
from app.core.cache import delete_keys, get_json, set_json
from app.core.database import get_db
from app.news.dtos import ConditionOptionDTO
from app.news.repositories import ConditionRepository

router = APIRouter(prefix="/api/conditions", tags=["conditions"])
CONDITIONS_CACHE_KEY = "reference:conditions:v1"
CONDITIONS_CACHE_TTL_SECONDS = 60 * 60


@router.get("", response_model=list[ConditionOptionDTO])
def list_conditions(
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_admin),
) -> list[ConditionOptionDTO]:
    cached = get_json(CONDITIONS_CACHE_KEY)

    if isinstance(cached, list):
        try:
            return [
                ConditionOptionDTO.model_validate(item)
                for item in cached
            ]
        except (TypeError, ValueError):
            delete_keys(CONDITIONS_CACHE_KEY)

    items = [
        ConditionOptionDTO.model_validate(condition)
        for condition in ConditionRepository(db).list_active()
    ]

    set_json(
        CONDITIONS_CACHE_KEY,
        [item.model_dump(mode="json") for item in items],
        CONDITIONS_CACHE_TTL_SECONDS,
    )

    return items
