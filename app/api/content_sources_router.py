from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.sources.actions import ListContentSourcesAction
from app.api.deps import require_super_admin
from app.core.database import get_db
from app.sources.dtos import (
    ContentSourceFilterData,
    ContentSourceListItemDTO,
)
from app.accounts.models import User
from app.sources.repositories import ContentSourceRepository

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
