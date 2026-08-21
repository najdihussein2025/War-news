from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.sources.actions import ListContentSourcesAction
from app.api.deps import require_admin
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
from app.logs.repositories import AuditLogRepository

router = APIRouter(prefix="/api/content-sources", tags=["content-sources"])


@router.get("", response_model=list[ContentSourceListItemDTO])
def list_content_sources(
    platform: str | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_admin),
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
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> ContentSourceBlockDTO:
    result = ContentSourceRepository(db).set_blocked(
        source_platform=source_platform,
        origin_account=origin_account,
        is_blocked=data.is_blocked,
        blocked_by=current_user.id,
    )
    AuditLogRepository(db).record(action="content_source.blocked" if data.is_blocked else "content_source.unblocked", target_type="content_source", target_id=f"{source_platform}/{origin_account}", actor_id=current_user.id, actor_name=current_user.full_name, client_ip=request.client.host if request.client else None, new_values=result.model_dump(mode="json"))
    return result


@router.get(
    "/{source_platform}/{origin_account}",
    response_model=ContentSourceDetailDTO,
)
def get_content_source(
    source_platform: str,
    origin_account: str,
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_admin),
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
