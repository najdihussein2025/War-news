from __future__ import annotations

import argparse

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.text_sanitizer import strip_emoji_and_pictographs
from app.news.models.air_violation import AirViolation
from app.news.models.incident import Incident


def sanitized_text(value: str | None) -> str:
    return strip_emoji_and_pictographs(value or "")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dry-run or apply emoji/pictograph cleanup to incident and air violation khabar fields.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist the cleaned khabar text. Omit for dry-run only.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        incidents = db.scalars(
            select(Incident).where(
                Incident.is_deleted.is_(False),
                Incident.khabar.is_not(None),
            )
        ).all()
        incident_updates = [
            incident for incident in incidents
            if sanitized_text(incident.khabar) != (incident.khabar or "")
        ]

        air_violations = db.scalars(select(AirViolation)).all()
        air_updates = [
            record for record in air_violations
            if sanitized_text(record.khabar) != (record.khabar or "")
        ]

        print(f"Incidents needing cleanup: {len(incident_updates)}")
        print(f"Air violations needing cleanup: {len(air_updates)}")

        if not args.apply:
            print("Dry run only. Re-run with --apply to persist changes.")
            return

        for incident in incident_updates:
            incident.khabar = sanitized_text(incident.khabar)
            db.add(incident)

        for record in air_updates:
            record.khabar = sanitized_text(record.khabar)
            db.add(record)

        db.commit()
        print("Cleanup applied successfully.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
