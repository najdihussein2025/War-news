from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.accounts.models import User
from app.api.deps import require_admin
from app.core.database import get_db
from app.news.dtos import ConditionOptionDTO
from app.news.repositories import ConditionRepository

router = APIRouter(prefix="/api/conditions", tags=["conditions"])


@router.get("", response_model=list[ConditionOptionDTO])
def list_conditions(
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_admin),
) -> list[ConditionOptionDTO]:
    return [
        ConditionOptionDTO.model_validate(condition)
        for condition in ConditionRepository(db).list_active()
    ]
