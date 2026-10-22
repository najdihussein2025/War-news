from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.accounts.models import User
from app.analytics.dtos.filters import Filters, get_filters
from app.analytics.services import analytics_service as service
from app.analytics.services import tab_service
from app.analytics.services.map_labels import village_labels
from app.analytics.services.export_service import build_workbook
from app.api.deps import require_admin
from app.core.database import get_db

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/meta")
def meta(db: Session = Depends(get_db), _user: User = Depends(require_admin)):
    return service.get_meta(db)


@router.get("/map")
def heat_map(flt: Filters = Depends(get_filters), db: Session = Depends(get_db), _user: User = Depends(require_admin)):
    return service.get_map(db, flt)


@router.get("/village-labels")
def map_village_labels(db: Session = Depends(get_db), _user: User = Depends(require_admin)):
    return village_labels(db)


@router.get("/kpis")
def kpis(flt: Filters = Depends(get_filters), db: Session = Depends(get_db), _user: User = Depends(require_admin)):
    return service.get_kpis(db, flt)


@router.get("/timeline")
def timeline(
    grain: Literal["day", "week", "month"] = Query("day"),
    flt: Filters = Depends(get_filters), db: Session = Depends(get_db), _user: User = Depends(require_admin),
):
    return service.get_timeline(db, flt, grain)


@router.get("/rankings")
def rankings(
    limit: int = Query(20, ge=1, le=100),
    flt: Filters = Depends(get_filters), db: Session = Depends(get_db), _user: User = Depends(require_admin),
):
    return service.get_rankings(db, flt, limit)


@router.get("/peaks")
def peaks(flt: Filters = Depends(get_filters), db: Session = Depends(get_db), _user: User = Depends(require_admin)):
    return service.get_peaks(db, flt)


@router.get("/matrix")
def matrix(flt: Filters = Depends(get_filters), db: Session = Depends(get_db), _user: User = Depends(require_admin)):
    return service.get_matrix(db, flt)


@router.get("/coverage")
def coverage(flt: Filters = Depends(get_filters), db: Session = Depends(get_db), _user: User = Depends(require_admin)):
    return service.get_coverage(db, flt)


@router.get("/quality")
def quality(flt: Filters = Depends(get_filters), db: Session = Depends(get_db), _user: User = Depends(require_admin)):
    return service.get_quality(db, flt)


@router.get("/incidents")
def incidents(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    flt: Filters = Depends(get_filters), db: Session = Depends(get_db), _user: User = Depends(require_admin),
):
    return service.get_incidents(db, flt, page, page_size)


@router.get("/tab/{tab}")
def tab_payload(
    tab: Literal["overview", "map", "incidents", "casualties", "air", "quality"],
    grain: Literal["day", "week", "month"] = Query("day"),
    flt: Filters = Depends(get_filters), db: Session = Depends(get_db), _user: User = Depends(require_admin),
):
    """Everything one Analytics tab draws, under the same filters (one request per tab)."""
    return tab_service.get_tab(db, tab, flt, grain)


@router.get("/export.xlsx")
def export_xlsx(flt: Filters = Depends(get_filters), db: Session = Depends(get_db), _user: User = Depends(require_admin)):
    content = build_workbook(db, flt)
    name = f"analytics_{flt.date_from}_{flt.date_to}.xlsx"
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/area/{code}")
def area(
    code: str,
    flt: Filters = Depends(get_filters), db: Session = Depends(get_db), _user: User = Depends(require_admin),
):
    if len(code) > 32:
        raise HTTPException(404, "Unknown area.")
    return service.get_area(db, code, flt)
