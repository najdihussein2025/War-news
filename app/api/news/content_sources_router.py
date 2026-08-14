from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.actions.news import ListContentSourcesAction
from app.api.dependencies import require_super_admin
from app.core.database import get_db
from app.dtos.news import ContentSourceFilterData, ContentSourceListItemDTO
from app.models.accounts import User
from app.repositories.news import ContentSourceRepository

router = APIRouter(prefix="/api/content-sources", tags=["content-sources"])


@router.get("", response_model=list[ContentSourceListItemDTO])
def list_content_sources(
    platform: str | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_super_admin),
) -> list[ContentSourceListItemDTO]:
    return ListContentSourcesAction(ContentSourceRepository(db)).execute(
        ContentSourceFilterData(platform=platform, search=search)
    )
