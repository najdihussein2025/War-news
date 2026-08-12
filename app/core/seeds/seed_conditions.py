import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.news import Condition

CONDITIONS_JSON_PATH = Path("Data/Conditions.json")


def _load_conditions() -> list[dict[str, Any]]:
    with CONDITIONS_JSON_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def seed_conditions(db: Session) -> tuple[int, int]:
    rows = _load_conditions()
    existing_actions_ar = set(db.scalars(select(Condition.action_ar)).all())
    seen_actions_ar: set[str] = set()
    inserted = 0
    skipped = 0

    for row in rows:
        action_ar = row["action_ar"]
        if action_ar in existing_actions_ar or action_ar in seen_actions_ar:
            skipped += 1
            continue

        db.add(
            Condition(
                action_en=row["action_en"],
                action_ar=action_ar,
                note=row.get("note"),
            )
        )
        seen_actions_ar.add(action_ar)
        inserted += 1

    db.commit()
    return inserted, skipped


def main() -> None:
    db = SessionLocal()
    try:
        inserted, skipped = seed_conditions(db)
        print(f"conditions inserted={inserted} skipped={skipped}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
