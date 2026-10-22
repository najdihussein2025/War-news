"""Read-only aggregate snapshot for browser verification; never changes auth or records."""
import json
import runpy
from datetime import date

from fastapi.encoders import jsonable_encoder
from app.analytics.dtos.filters import Filters
from app.analytics.services import analytics_service as service, tab_service
from app.core.database import SessionLocal

with SessionLocal() as db:
    result = {"meta": service.get_meta(db), "levels": {}}
    flt = Filters(date_from=date(2026, 9, 23), date_to=date(2026, 10, 22))
    for level in ("mohafaza", "caza", "village"):
        current = flt.model_copy(update={"level": level})
        result["levels"][level] = {
            "overview": tab_service.get_tab(db, "overview", current, "day"),
            "map": service.get_map(db, current), "kpis": service.get_kpis(db, current),
            "rankings": service.get_rankings(db, current, 10),
        }
    result["labels"] = runpy.run_path("/tmp/map_labels.py")["village_labels"](db)
    result["area"] = service.get_area(db, "LB43", flt)
    print(json.dumps(jsonable_encoder(result), ensure_ascii=True))
