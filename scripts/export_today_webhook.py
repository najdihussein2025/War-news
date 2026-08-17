import csv
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.core.database import SessionLocal
from app.news.models.raw_message import RawMessage
from app.sources.models.source import Source


BEIRUT = ZoneInfo("Asia/Beirut")
start = datetime(2026, 8, 17, 8, 0, tzinfo=BEIRUT)
end = datetime.now(BEIRUT)
output = Path("Data/webhook_2026-08-17_0800_to_now_beirut.csv")

statement = (
    select(RawMessage)
    .join(Source, Source.id == RawMessage.source_id)
    .where(
        Source.name == "CNRS Webhook",
        RawMessage.received_at >= start,
        RawMessage.received_at <= end,
    )
    .order_by(RawMessage.received_at)
)

with SessionLocal() as db:
    records = list(db.scalars(statement))

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
                "id": record.id,
                "external_message_id": record.external_message_id,
                "source_platform": record.source_platform,
                "source_name": record.source_name,
                "message_datetime_beirut": (
                    record.message_datetime.astimezone(BEIRUT).isoformat()
                    if record.message_datetime
                    else ""
                ),
                "received_at_beirut": record.received_at.astimezone(BEIRUT).isoformat(),
                "status": record.status.value,
                "raw_text": record.raw_text,
            }
        )

print(f"start={start.isoformat()}")
print(f"end={end.isoformat()}")
print(f"records={len(records)}")
print(f"output={output}")
