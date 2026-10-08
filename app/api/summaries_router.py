from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.accounts.models import User
from app.api.deps import require_admin
from app.core.database import get_db
from app.news.services.summaries.review_service import (
    ResolveRequest,
    ReviewError,
    dismiss_review_task,
    list_summaries,
    resolve_review_task,
    summary_detail,
)

router = APIRouter(prefix="/api/summaries", tags=["summaries"])


def _http(error: ReviewError) -> HTTPException:
    return HTTPException(status_code=error.status, detail=str(error))


def _detail_or_404(db: Session, summary_id: int) -> dict[str, Any]:
    detail = summary_detail(db, summary_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Summary not found.")
    return detail


@router.get("")
def get_summaries(
    status: str | None = None,
    channel: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    has_open_task: bool | None = None,
    include_hidden: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_admin),
) -> dict[str, Any]:
    try:
        items, total = list_summaries(
            db, status=status, channel=channel, date_from=date_from, date_to=date_to,
            has_open_task=has_open_task, include_hidden=include_hidden, page=page, page_size=page_size,
        )
    except ReviewError as error:
        raise _http(error) from error
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/{summary_id}")
def get_summary(
    summary_id: int,
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_admin),
) -> dict[str, Any]:
    return _detail_or_404(db, summary_id)


@router.post("/{summary_id}/review-task/resolve")
def resolve_task(
    summary_id: int,
    payload: ResolveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict[str, Any]:
    try:
        outcome = resolve_review_task(db, summary_id, payload, current_user.id)
        db.commit()
    except ReviewError as error:
        db.rollback()
        raise _http(error) from error
    except Exception:
        db.rollback()
        raise
    return {
        "handled_item_ids": outcome.handled_item_ids,
        "new_item_ids": outcome.new_item_ids,
        "alias_saved_for_items": outcome.alias_saved,
        "mappings_saved": outcome.mapping_saved,
        "summary": _detail_or_404(db, summary_id),
    }


@router.post("/{summary_id}/review-task/dismiss")
def dismiss_task(
    summary_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict[str, Any]:
    try:
        dismiss_review_task(db, summary_id, current_user.id)
        db.commit()
    except ReviewError as error:
        db.rollback()
        raise _http(error) from error
    except Exception:
        db.rollback()
        raise
    return {"summary": _detail_or_404(db, summary_id)}
