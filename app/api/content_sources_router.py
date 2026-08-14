from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.sources.actions import ListContentSourcesAction
from app.api.deps import require_super_admin
from app.core.database import get_db
from app.sources.dtos import (
    ContentSourceBlockDTO,
    ContentSourceBlockUpdateData,
    ContentSourceDetailDTO,
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


@router.patch(
    "/{source_platform}/{origin_account}/block",
    response_model=ContentSourceBlockDTO,
)
def set_content_source_blocked(
    source_platform: str,
    origin_account: str,
    data: ContentSourceBlockUpdateData,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
) -> ContentSourceBlockDTO:
    return ContentSourceRepository(db).set_blocked(
        source_platform=source_platform,
        origin_account=origin_account,
        is_blocked=data.is_blocked,
        blocked_by=current_user.id,
    )


@router.get(
    "/{source_platform}/{origin_account}",
    response_model=ContentSourceDetailDTO,
)
def get_content_source(
    source_platform: str,
    origin_account: str,
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_super_admin),
) -> ContentSourceDetailDTO:
    detail = ContentSourceRepository(db).get_detail(
        source_platform=source_platform,
        origin_account=origin_account,
    )
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Content source was not found.",
        )
    return detail
