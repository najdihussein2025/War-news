"""Validated query filters shared by every analytics endpoint."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.analytics.constants import MAX_RANGE_DAYS
from app.core.database import get_db

Level = Literal["mohafaza", "caza", "village"]
Metric = Literal["incidents", "deaths", "injuries", "casualties", "breaches"]
Grain = Literal["day", "week", "month"]
BEIRUT = ZoneInfo("Asia/Beirut")


def today_beirut() -> date:
    return datetime.now(BEIRUT).date()


class Filters(BaseModel):
    model_config = ConfigDict(frozen=True)

    date_from: date
    date_to: date
    level: Level = "mohafaza"
    area_code: str | None = None
    area_level: Level | None = None
    family: tuple[str, ...] = ()
    condition_id: tuple[int, ...] = ()
    include_pending: bool = False
    metric: Metric = "incidents"

    @property
    def days(self) -> int:
        return (self.date_to - self.date_from).days + 1

    def previous_period(self) -> "Filters":
        span = timedelta(days=self.days)
        return self.model_copy(update={"date_from": self.date_from - span, "date_to": self.date_from - timedelta(days=1)})

    def cache_params(self) -> dict:
        return {
            "date_from": self.date_from.isoformat(), "date_to": self.date_to.isoformat(),
            "level": self.level, "area_code": self.area_code, "family": sorted(self.family),
            "condition_id": sorted(self.condition_id), "include_pending": self.include_pending,
            "metric": self.metric,
        }


def params_hash(params: dict) -> str:
    return hashlib.sha1(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()[:24]


def get_filters(
    date_from: date | None = Query(None, description="Inclusive start; default 29 days before date_to"),
    date_to: date | None = Query(None, description="Inclusive end; default today (Asia/Beirut)"),
    level: Level = Query("mohafaza"),
    area_code: str | None = Query(None, max_length=32),
    family: list[str] = Query(default=[]),
    condition_id: list[int] = Query(default=[]),
    include_pending: bool = Query(False),
    metric: Metric = Query("incidents"),
    db: Session = Depends(get_db),
) -> Filters:
    end = date_to or today_beirut()
    start = date_from or (end - timedelta(days=29))
    if start > end:
        raise HTTPException(422, "date_from must not be after date_to.")
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise HTTPException(422, f"The date range may not exceed {MAX_RANGE_DAYS} days.")

    area_level: str | None = None
    if area_code is not None:
        area_level = db.execute(text("SELECT level FROM admin_areas WHERE code = :c"), {"c": area_code}).scalar()
        if area_level is None:
            raise HTTPException(422, f"Unknown area_code {area_code!r}.")
    if family:
        known = {r[0] for r in db.execute(text("SELECT code FROM action_families"))}
        bad = sorted(set(family) - known)
        if bad:
            raise HTTPException(422, f"Unknown family code(s): {', '.join(bad)}.")
    if condition_id:
        known_ids = {r[0] for r in db.execute(text("SELECT id FROM conditions WHERE id = ANY(:ids)"), {"ids": list(condition_id)})}
        bad_ids = sorted(set(condition_id) - known_ids)
        if bad_ids:
            raise HTTPException(422, f"Unknown condition_id(s): {', '.join(map(str, bad_ids))}.")
    return Filters(
        date_from=start, date_to=end, level=level, area_code=area_code, area_level=area_level,
        family=tuple(family), condition_id=tuple(condition_id), include_pending=include_pending,
        metric=metric,
    )
