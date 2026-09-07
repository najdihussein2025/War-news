import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.news.models import EmergencyOrganization

EMERGENCY_ORGANIZATIONS_JSON_PATH = Path("Data/EmergencyOrganizations.json")


def _load_emergency_organizations() -> list[dict[str, Any]]:
    with EMERGENCY_ORGANIZATIONS_JSON_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def seed_emergency_organizations(db: Session) -> tuple[int, int]:
    rows = _load_emergency_organizations()
    existing_names_ar = set(db.scalars(select(EmergencyOrganization.name_ar)).all())
    seen_names_ar: set[str] = set()
    inserted = 0
    skipped = 0

    for row in rows:
        name_ar = row["name_ar"]
        if name_ar in existing_names_ar or name_ar in seen_names_ar:
            skipped += 1
            continue

        db.add(
            EmergencyOrganization(
                name_ar=name_ar,
                name_en=row["name_en"],
                aliases=list(row.get("aliases") or []),
                org_type=row.get("org_type"),
            )
        )
        seen_names_ar.add(name_ar)
        inserted += 1

    db.commit()
    return inserted, skipped


def main() -> None:
    db = SessionLocal()
    try:
        inserted, skipped = seed_emergency_organizations(db)
        print(f"emergency_organizations inserted={inserted} skipped={skipped}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
