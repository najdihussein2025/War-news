import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401
from app.core.database import SessionLocal
from app.core.text_normalization import normalize_arabic_text
from app.news.models import Village
from app.news.models.village_location_alias import VillageLocationAlias

VILLAGE_LOCATION_ALIASES_JSON_PATH = Path("Data/VillageLocationAliases.json")


def _load_alias_rows() -> list[dict[str, Any]]:
    with VILLAGE_LOCATION_ALIASES_JSON_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def seed_village_location_aliases(db: Session) -> tuple[int, int, int]:
    """Insert proposed aliases. Returns (inserted, skipped, missing_parent)."""
    rows = _load_alias_rows()
    existing_norms = set(
        db.scalars(select(VillageLocationAlias.alias_normalized)).all()
    )
    villages_by_acs = {
        code: village_id
        for code, village_id in db.execute(
            select(Village.acs_code, Village.id)
        ).all()
    }

    inserted = 0
    skipped = 0
    missing_parent = 0
    seen_norms: set[str] = set()

    for row in rows:
        alias_text = str(row["alias_text"]).strip()
        normalized = normalize_arabic_text(alias_text)
        if not normalized:
            skipped += 1
            continue
        if normalized in existing_norms or normalized in seen_norms:
            skipped += 1
            continue

        parent_acs = int(row["parent_acs_code"])
        village_id = villages_by_acs.get(parent_acs)
        if village_id is None:
            missing_parent += 1
            continue

        db.add(
            VillageLocationAlias(
                alias_text=alias_text,
                alias_normalized=normalized,
                village_id=village_id,
                note=row.get("note"),
            )
        )
        seen_norms.add(normalized)
        inserted += 1

    db.commit()
    return inserted, skipped, missing_parent


def main() -> None:
    db = SessionLocal()
    try:
        inserted, skipped, missing = seed_village_location_aliases(db)
        print(
            "village_location_aliases "
            f"inserted={inserted} skipped={skipped} missing_parent={missing}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
