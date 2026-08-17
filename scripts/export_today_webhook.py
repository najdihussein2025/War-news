import csv
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.core.database import SessionLocal


BEIRUT = ZoneInfo("Asia/Beirut")
start = datetime(2026, 8, 17, 8, 0, tzinfo=BEIRUT)
end = datetime.now(BEIRUT)
output = Path("Data/webhook_2026-08-17_0800_to_now_beirut.csv")

statement = text(
    """
    SELECT rm.id, rm.external_message_id, rm.source_platform, rm.source_name,
           rm.message_datetime, rm.received_at, rm.status::text AS status,
           rm.raw_text
    FROM raw_messages AS rm
    JOIN sources AS s ON s.id = rm.source_id
    WHERE s.name = 'CNRS Webhook'
      AND rm.received_at >= :start
      AND rm.received_at <= :end
    ORDER BY rm.received_at
    """
)

with SessionLocal() as db:
    records = list(db.execute(statement, {"start": start, "end": end}).mappings())

output.parent.mkdir(parents=True, exist_ok=True)
with output.open("w", newline="", encoding="utf-8-sig") as handle:
    writer = csv.DictWriter(
        handle,
        fieldnames=[
            "id",
            "external_message_id",
            "source_platform",
            "source_name",
            "message_datetime_beirut",
            "received_at_beirut",
            "status",
            "raw_text",
        ],
    )
    writer.writeheader()
    for record in records:
        writer.writerow(
            {
                "id": record["id"],
                "external_message_id": record["external_message_id"],
                "source_platform": record["source_platform"],
                "source_name": record["source_name"],
                "message_datetime_beirut": (
                    record["message_datetime"].astimezone(BEIRUT).isoformat()
                    if record["message_datetime"]
                    else ""
                ),
                "received_at_beirut": record["received_at"].astimezone(BEIRUT).isoformat(),
                "status": record["status"],
                "raw_text": record["raw_text"],
            }
        )

print(f"start={start.isoformat()}")
print(f"end={end.isoformat()}")
print(f"records={len(records)}")
print(f"output={output}")
