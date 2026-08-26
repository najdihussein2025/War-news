from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.news.models.sweep_cursor import SweepCursor


class SweepCursorRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, sweep_name: str) -> int:
        row = self.db.get(SweepCursor, sweep_name)
        return 0 if row is None else int(row.last_processed_id)

    def get_or_create(self, sweep_name: str) -> int:
        return self.get(sweep_name)

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
