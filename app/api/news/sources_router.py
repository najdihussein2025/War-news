from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.actions.news import ListSourcesAction
from app.api.dependencies import require_super_admin
from app.core.database import get_db
from app.dtos.news import SourceListItemDTO
from app.models.accounts import User
from app.repositories.news import SourceRepository

router = APIRouter(prefix="/api/sources", tags=["sources"])


@router.get("", response_model=list[SourceListItemDTO])
def list_sources(
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_super_admin),
) -> list[SourceListItemDTO]:
    return ListSourcesAction(SourceRepository(db)).execute()
