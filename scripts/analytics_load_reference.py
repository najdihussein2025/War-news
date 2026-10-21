"""Load analytics reference data (admin areas, village links, action families).

Dry-run by default; writes only with --apply. Idempotent.

    python -m scripts.analytics_load_reference            # dry-run
    python -m scripts.analytics_load_reference --apply
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from app.analytics.services.reference_loader import (
    FAMILIES_PATH,
    GEO_DIR,
    ReferencePlan,
    apply_reference,
    plan_reference,
)
from app.core.database import SessionLocal
from app.core.logging_config import configure_logging

logger = logging.getLogger(__name__)
SWEEP_NAME = "analytics_load_reference"


def _print_plan(plan: ReferencePlan) -> None:
    counts = plan.counts_by_level
    print("admin_areas to upsert: " + ", ".join(f"{level}={n}" for level, n in counts.items()))
    disputed = [a.code for a in plan.areas if a.is_disputed]
    print(f"disputed areas: {len(disputed)}")
    total = len(plan.villages_linked) + len(plan.villages_unlinked)
    print(f"villages linked: {len(plan.villages_linked)} / {total}")
    if plan.villages_unlinked:
        print("villages without a geojson polygon:")
        for village_id, acs_code, name in plan.villages_unlinked:
            print(f"  id={village_id} acs_code={acs_code} name={name}")
    print("condition -> family:")
    for m in sorted(plan.mappings, key=lambda m: m.condition_id):
        print(f"  {m.condition_id:>4}  {m.family_code:<18} {m.action_en}  [{m.matched_by}]")
    if plan.unmapped_conditions:
        print("UNMAPPED conditions (add them to Data/analytics/action_families.json):")
        for condition_id, action_en, action_ar in plan.unmapped_conditions:
            print(f"  {condition_id}: {action_en} / {action_ar}")
    if plan.mapping_entries_without_condition:
        print("mapping entries with no matching condition row (ignored): "
              + ", ".join(plan.mapping_entries_without_condition))


def main() -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write changes (default is dry-run)")
    parser.add_argument("--geo-dir", type=Path, default=GEO_DIR)
    parser.add_argument("--families", type=Path, default=FAMILIES_PATH)
    args = parser.parse_args()

    failed = 0
    processed = 0
    try:
        with SessionLocal() as db:
            plan = plan_reference(db, args.geo_dir, args.families)
            _print_plan(plan)
            processed = len(plan.areas) + len(plan.mappings)
            if plan.unmapped_conditions:
                failed = len(plan.unmapped_conditions)
            elif args.apply:
                apply_reference(db, plan)
                db.commit()
                print("applied.")
            else:
                print("dry-run: nothing written (use --apply).")
    except Exception:
        logger.exception("analytics reference load failed")
        return 1

    line = f"Analytics reference load processed={processed} succeeded={processed - failed} failed={failed}"
    logger.info("%s sweep_name=%s", line, SWEEP_NAME)
    print(line, flush=True)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
