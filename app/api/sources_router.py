from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.sources.actions import (
    GetSourceAction,
    ListSourcesAction,
    SetSourceActiveAction,
    SourceNotFoundError,
)
from app.api.deps import require_super_admin
from app.core.database import get_db
from app.sources.dtos import (
    SourceActiveUpdateData,
    SourceDetailDTO,
    SourceListItemDTO,
    SourceLookupData,
)
from app.accounts.models import User
from app.sources.repositories import SourceRepository

router = APIRouter(prefix="/api/sources", tags=["sources"])


@router.get("", response_model=list[SourceListItemDTO])
def list_sources(
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_super_admin),
) -> list[SourceListItemDTO]:
    return ListSourcesAction(SourceRepository(db)).execute()


@router.get("/{source_id}", response_model=SourceDetailDTO)
def get_source(
    source_id: int,
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_super_admin),
) -> SourceDetailDTO:
    try:
        return GetSourceAction(SourceRepository(db)).execute(
            SourceLookupData(source_id=source_id)
        )
    except SourceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


def _set_source_active(
    source_id: int,
    is_active: bool,
    db: Session,
) -> SourceDetailDTO:
    try:
        return SetSourceActiveAction(SourceRepository(db)).execute(
            SourceActiveUpdateData(source_id=source_id, is_active=is_active)
        )
    except SourceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post("/{source_id}/pause", response_model=SourceDetailDTO)
def pause_source(
    source_id: int,
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_super_admin),
) -> SourceDetailDTO:
    return _set_source_active(source_id, False, db)


@router.post("/{source_id}/resume", response_model=SourceDetailDTO)
def resume_source(
    source_id: int,
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_super_admin),
) -> SourceDetailDTO:
    return _set_source_active(source_id, True, db)
