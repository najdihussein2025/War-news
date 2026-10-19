"""Preview or backfill Arabic casualty verification reasons.

Dry-run is the default. Pass --apply explicitly to write to the configured
database; production execution requires a separate reviewed runbook.
"""

from __future__ import annotations

import argparse

from sqlalchemy import select

from app.core.database import SessionLocal
from app.news.models import Incident
from app.news.services.casualty_flag_evaluator import CasualtyFlagEvaluator


def run(*, apply: bool = False) -> dict[str, int]:
    summary = {"processed": 0, "succeeded": 0, "failed": 0}
    with SessionLocal() as db:
        incident_ids = list(db.scalars(select(Incident.id).where(
            Incident.is_deleted.is_(False),
            Incident.casualty_status.in_(("count_missing", "aggregate_only")),
        )))
        evaluator = CasualtyFlagEvaluator(db, enabled=True)
        for incident_id in incident_ids:
            summary["processed"] += 1
            try:
                evaluator.evaluate_incident(incident_id)
                summary["succeeded"] += 1
            except Exception:
                summary["failed"] += 1
        if apply:
            db.commit()
        else:
            db.rollback()
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(run(apply=args.apply))
