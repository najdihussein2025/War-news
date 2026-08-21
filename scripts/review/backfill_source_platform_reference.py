from __future__ import annotations

import argparse

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.database import SessionLocal
from app.logs import models as _log_models  # noqa: F401
from app.news.models.raw_message import RawMessage
from app.sources.models.source_platform import SourcePlatform
from app.sources import models as _source_models  # noqa: F401


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dry-run or apply source_platform/source_name backfill into raw_messages.source_platform_id.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist source_platform rows and raw_messages.source_platform_id updates.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        candidates = db.scalars(
            select(RawMessage).where(
                RawMessage.source_platform_id.is_(None),
                RawMessage.source_platform.is_not(None),
                RawMessage.source_name.is_not(None),
                RawMessage.source_platform != "",
                RawMessage.source_name != "",
            )
        ).all()

        pairs = sorted({(row.source_platform, row.source_name) for row in candidates})
        existing_pairs = {
            (platform, name)
            for platform, name in db.execute(
                select(SourcePlatform.platform, SourcePlatform.name)
            ).all()
        }
        missing_pairs = [pair for pair in pairs if pair not in existing_pairs]

        print(f"Raw messages backfillable: {len(candidates)}")
        print(f"Distinct missing source_platform pairs to insert: {len(missing_pairs)}")

        if not args.apply:
            print("Dry run only. Re-run with --apply to persist changes.")
            return

        for platform, name in missing_pairs:
            db.execute(
                insert(SourcePlatform)
                .values(platform=platform, name=name)
                .on_conflict_do_nothing(index_elements=["platform", "name"])
            )

        platform_ids = {
            (platform, name): platform_id
            for platform_id, platform, name in db.execute(
                select(SourcePlatform.id, SourcePlatform.platform, SourcePlatform.name)
            ).all()
        }

        for row in candidates:
            row.source_platform_id = platform_ids[(row.source_platform, row.source_name)]
            db.add(row)

        db.commit()
        print("Backfill applied successfully.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
