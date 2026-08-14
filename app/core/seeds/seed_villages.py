import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.news.models import Village

VILLAGES_JSON_PATH = Path("Data/Villages.json")


def _load_villages() -> list[dict[str, Any]]:
    with VILLAGES_JSON_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def seed_villages(db: Session) -> tuple[int, int]:
    rows = _load_villages()
    existing_codes = set(db.scalars(select(Village.acs_code)).all())
    seen_codes: set[int] = set()
    inserted = 0
    skipped = 0

    for row in rows:
        acs_code = row["acs_code"]
        if acs_code in existing_codes or acs_code in seen_codes:
            skipped += 1
            continue

        db.add(
            Village(
                acs_code=acs_code,
                acs_name=row.get("acs_name"),
                cad_name=row.get("cad_name"),
                ref_name_en=row.get("ref_name_en"),
                ref_name_ar=row.get("ref_name_ar"),
                caza_en=row.get("caza_en"),
                caza_ar=row.get("caza_ar"),
                mohafaza_en=row.get("mohafaza_en"),
                mohafaza_ar=row.get("mohafaza_ar"),
                coord_x=row.get("coord_x"),
                coord_y=row.get("coord_y"),
            )
        )
        seen_codes.add(acs_code)
        inserted += 1

    db.commit()
    return inserted, skipped


def main() -> None:
    db = SessionLocal()
    try:
        inserted, skipped = seed_villages(db)
        print(f"villages inserted={inserted} skipped={skipped}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
