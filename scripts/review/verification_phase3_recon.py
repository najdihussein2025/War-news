"""Read-only Phase 3 verification queue recon.

The live database may still contain pre-recompute ``needs_verification`` rows.
This script reports the stored queue and the dry-run projected queue using the
same recompute logic as ``scripts/recompute_verification_status.py``.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.news.models import Incident, RawMessage
from app.news.repositories.condition_repository import ConditionRepository
from app.news.repositories.village_repository import VillageRepository
from app.news.services.matching.matching_service import MatchingService
from scripts.recompute_verification_status import _reason_bucket, recompute


@dataclass
class Bucket:
    incidents: int = 0
    raw_message_ids: set[int] | None = None

    def add(self, raw_message_id: int | None) -> None:
        self.incidents += 1
        if self.raw_message_ids is None:
            self.raw_message_ids = set()
        if raw_message_id is not None:
            self.raw_message_ids.add(raw_message_id)

    @property
    def bulletins(self) -> int:
        return len(self.raw_message_ids or ())


def main() -> int:
    db = SessionLocal()
    matcher = MatchingService(VillageRepository(db), ConditionRepository(db))
    projected: dict[str, Bucket] = defaultdict(Bucket)
    live: dict[str, Bucket] = defaultdict(Bucket)
    processed = failed = 0
    try:
        stored = list(
            db.scalars(
                select(Incident)
                .where(
                    Incident.is_deleted.is_(False),
                    Incident.verification_status == "needs_verification",
                )
                .order_by(Incident.created_at.asc(), Incident.id.asc())
            ).all()
        )
        for incident in stored:
            live[_reason_bucket(incident.verification_reason)].add(
                incident.raw_message_id
            )
            processed += 1
            if processed == 1 or processed % 100 == 0:
                print(f"progress processed={processed}/{len(stored)}", flush=True)
            raw = db.get(RawMessage, incident.raw_message_id)
            if raw is None:
                failed += 1
                continue
            try:
                outcome = recompute(incident, raw, matcher)
                if outcome.status == "needs_verification":
                    projected[_reason_bucket(outcome.reason)].add(
                        incident.raw_message_id
                    )
            except Exception as exc:
                failed += 1
                print(f"ERROR incident={incident.id}: {exc}", flush=True)
            finally:
                db.rollback()

        live_incidents = sum(bucket.incidents for bucket in live.values())
        live_bulletins = (
            db.scalar(
                select(func.count(func.distinct(Incident.raw_message_id))).where(
                    Incident.is_deleted.is_(False),
                    Incident.verification_status == "needs_verification",
                    Incident.raw_message_id.is_not(None),
                )
            )
            or 0
        )
        projected_incidents = sum(bucket.incidents for bucket in projected.values())
        projected_bulletins = len(
            {
                raw_message_id
                for bucket in projected.values()
                for raw_message_id in (bucket.raw_message_ids or set())
            }
        )

        print("\n## Stored queue")
        print(f"incidents={live_incidents} bulletins={int(live_bulletins)}")
        print("| Reason bucket | Incidents | Bulletins |")
        print("|---|---:|---:|")
        for reason, bucket in sorted(
            live.items(), key=lambda item: (-item[1].incidents, item[0])
        ):
            print(f"| {reason} | {bucket.incidents} | {bucket.bulletins} |")

        print("\n## Dry-run projected queue")
        print(
            f"incidents={projected_incidents} bulletins={projected_bulletins} "
            f"processed={processed} failed={failed}"
        )
        print("| Reason bucket | Incidents | Bulletins |")
        print("|---|---:|---:|")
        for reason, bucket in sorted(
            projected.items(), key=lambda item: (-item[1].incidents, item[0])
        ):
            print(f"| {reason} | {bucket.incidents} | {bucket.bulletins} |")
        return 1 if failed else 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
