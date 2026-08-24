from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.news.models.sweep_cursor import SweepCursor


class SweepCursorRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_or_create(self, sweep_name: str) -> int:
        row = self.db.get(SweepCursor, sweep_name)
        if row is None:
            row = SweepCursor(sweep_name=sweep_name, last_processed_id=0)
            self.db.add(row)
            self.db.commit()
            self.db.refresh(row)
        return int(row.last_processed_id)

    def save(self, sweep_name: str, last_processed_id: int) -> None:
        row = self.db.get(SweepCursor, sweep_name)
        now = datetime.now(timezone.utc)
        if row is None:
            self.db.add(
                SweepCursor(
                    sweep_name=sweep_name,
                    last_processed_id=last_processed_id,
                    updated_at=now,
                )
            )
        else:
            row.last_processed_id = last_processed_id
            row.updated_at = now
            self.db.add(row)
        self.db.commit()
