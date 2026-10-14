"""Export read-only casualty regression fixtures from the connected database."""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.news.models  # noqa: F401
import app.sources.models  # noqa: F401
from app.core.database import SessionLocal
from app.news.models.raw_message import RawMessage
from app.news.models.incident_update import IncidentUpdate

RAW_IDS = (42520, 28588, 8986, 32756, 8957, 30033, 5050, 5052, 5310, 31308, 4040)
EXPECTED = {
    42520: {"casualty_status": "none", "casualties": []},
    28588: {"casualty_status": "none", "casualties": []},
    32756: {"casualty_status": "per_village_exact", "villages": {"الريحان": {"deaths": 1}, "النبطية حي المسلخ": {"injuries": 9, "children_injuries": 2, "female_injuries": 3}, "النبطية الفوقا": {"injuries": 1}}},
    8986: {"casualty_status": "none", "casualties": []},
    30033: {"deaths": 9, "injuries": 5, "conflict": "headline_and_body_deaths"},
    31308: {"villages": {"كفررمان": {"injuries": 5}, "عربصاليم": {"deaths": 2, "male_deaths": None}}},
    8957: {"villages": {"النبطية حي المسلخ": {"injuries": 9, "children_injuries": 2, "female_injuries": 3}, "النبطية الفوقا": {"injuries": 1}, "الريحان": {"deaths": 1}}},
    4040: {"villages": {"كفررمان": {"injuries": 5}}},
    5050: {"casualty_status": "per_village_exact", "resolver": "headline_equals_parts_use_parts", "casualties": [{"village": "Kfarroumane", "deaths": 9, "injuries": 13}]},
    5052: {"casualty_status": "per_village_exact", "casualties": [{"village": "Kfarroumane", "deaths": 8, "injuries": 11}]},
    5310: {"casualty_status": "per_village_exact", "casualties": [{"village": "Kfarroumane", "deaths": 1, "injuries": None}]},
}


def main() -> None:
    destination = Path("tests/fixtures/casualty_gold")
    destination.mkdir(parents=True, exist_ok=True)
    db = SessionLocal()
    try:
        messages = {item.id: item for item in db.scalars(select(RawMessage).where(RawMessage.id.in_(RAW_IDS)))}
        for raw_id in RAW_IDS:
            raw = messages.get(raw_id)
            if raw is None:
                snapshot = db.scalars(select(IncidentUpdate).where(IncidentUpdate.new_values["merged_from"]["raw_message_id"].astext == str(raw_id)).order_by(IncidentUpdate.created_at)).first()
                merged = (snapshot.new_values or {}).get("merged_from") if snapshot else None
                if not isinstance(merged, dict) or not isinstance(merged.get("khabar"), str):
                    print(f"missing raw_id={raw_id}")
                    continue
                payload = {"raw_id": raw_id, "source_id": None, "received_at": snapshot.created_at.isoformat(), "raw_text": merged["khabar"], "origin": "merged_from_snapshot", "source": merged.get("channel"), "expected": EXPECTED.get(raw_id)}
                (destination / f"{raw_id}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"exported snapshot raw_id={raw_id}")
                continue
            payload = {"raw_id": raw.id, "source_id": raw.source_id, "received_at": raw.received_at.isoformat(), "raw_text": raw.raw_text, "origin": "raw_messages", "expected": EXPECTED.get(raw_id)}
            (destination / f"{raw_id}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"exported raw_id={raw_id}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
