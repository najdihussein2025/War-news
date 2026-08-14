from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.news.source import Source, SourceType

CNRS_WEBHOOK_SECRET_REF = "CNRS_WEBHOOK_SECRET"

CNRS_SOURCES: tuple[dict[str, Any], ...] = (
    {
        "type": SourceType.api,
        "name": "CNRS Webhook",
        "external_id": "cnrs_webhook",
        "config": {"delivery_method": "webhook"},
        "last_cursor": None,
        "auth_secret_ref": CNRS_WEBHOOK_SECRET_REF,
        "is_active": True,
    },
)


def seed_cnrs_sources(db: Session) -> list[tuple[Source, bool]]:
    results: list[tuple[Source, bool]] = []

    for source_data in CNRS_SOURCES:
        existing_source = db.scalar(
            select(Source).where(Source.external_id == source_data["external_id"])
        )
        if existing_source is not None:
            results.append((existing_source, False))
            continue

        source = Source(**source_data)
        db.add(source)
        db.flush()
        results.append((source, True))

    db.commit()
    return results


def main() -> None:
    db = SessionLocal()
    try:
        for source, inserted in seed_cnrs_sources(db):
            action = "inserted" if inserted else "skipped"
            print(
                f"{action}: id={source.id}, "
                f"external_id={source.external_id}, "
                f"config={source.config}"
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
