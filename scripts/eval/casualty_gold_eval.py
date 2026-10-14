"""Run the real casualty pipeline against gold fixtures in ``war_news_test``.

This is deliberately opt-in: it creates isolated fixture messages only with
``--run`` and refuses every database except ``war_news_test``.  It is not a
pytest target and must never be invoked by tests.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select, text

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.news.models  # noqa: F401
import app.sources.models  # noqa: F401
from app.core.database import SessionLocal
from app.news.models import MessageStatus
from app.news.models.incident import Incident
from app.news.models.raw_message import RawMessage
from app.sources.models.source import Source

FIXTURES = Path("tests/fixtures/casualty_gold")
REPORT_DIR = Path("Docs/eval")


def _flatten(value: Any, path: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, child in value.items():
            output.update(_flatten(child, f"{path}.{key}" if path else key))
        return output
    if isinstance(value, list):
        output = {}
        for index, child in enumerate(value):
            output.update(_flatten(child, f"{path}[{index}]"))
        return output
    return {path: value}


def _fixture_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("expected") is None:
        raise ValueError(f"fixture {path} has no expected result")
    return payload


def _ensure_fixture_message(db: Any, fixture: dict[str, Any]) -> RawMessage:
    """Create a uniquely named parsed message in the test database only."""
    external_id = f"casualty-gold-{fixture['raw_id']}"
    existing = db.scalar(select(RawMessage).where(RawMessage.external_message_id == external_id))
    if existing is not None:
        return existing
    source = db.get(Source, fixture.get("source_id")) if fixture.get("source_id") else None
    source = source or db.scalar(select(Source).order_by(Source.id))
    if source is None:
        raise RuntimeError("war_news_test has no source row for gold fixture input")
    message = RawMessage(
        source_id=source.id,
        external_message_id=external_id,
        source_name="casualty_gold_eval",
        source_platform="fixture",
        raw_text=fixture["raw_text"],
        raw_payload={"casualty_gold_fixture": fixture["raw_id"], "origin": fixture["origin"]},
        received_at=datetime.now(timezone.utc),
        status=MessageStatus.parsed,
        filter_result={"verdict": "relevant", "backend": "casualty_gold_eval"},
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def _actual_values(db: Any, message: RawMessage) -> dict[str, Any]:
    incidents = list(db.scalars(select(Incident).where(Incident.raw_message_id == message.id)))
    return {
        "extraction": message.extraction_result,
        "incidents": [
            {
                "village": incident.village_display_name,
                "deaths": incident.deaths,
                "injuries": incident.injuries,
                "total_deaths": incident.total_deaths,
                "total_injuries": incident.total_injuries,
                "casualty_status": incident.casualty_status,
            }
            for incident in incidents
        ],
    }


def _compare(expected: dict[str, Any], actual: dict[str, Any]) -> list[dict[str, Any]]:
    """Report every expected leaf and whether it occurs in real stage output."""
    actual_text = json.dumps(actual, ensure_ascii=False, sort_keys=True)
    return [
        {"field": field, "expected": value, "observed": "present" if json.dumps(value, ensure_ascii=False) in actual_text else "missing"}
        for field, value in _flatten(expected).items()
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="permit fixture writes and pipeline calls in war_news_test")
    args = parser.parse_args()
    if not args.run:
        raise SystemExit("Refusing to run. Use --run only against war_news_test.")

    db = SessionLocal()
    try:
        database = db.execute(text("select current_database()")).scalar_one()
        if database != "war_news_test":
            raise SystemExit(f"Refusing live casualty eval against {database!r}; requires 'war_news_test'.")
        fixtures = [_fixture_payload(path) for path in sorted(FIXTURES.glob("*.json"))]
        messages = [_ensure_fixture_message(db, fixture) for fixture in fixtures]
    finally:
        db.close()

    # Imported only after the database guard: these paths call configured LLMs.
    from app.news.services.pipeline.pipeline_llm_workers import (  # noqa: PLC0415
        run_tier1_extraction_for_message,
        run_tier2_detail_fill_for_message,
    )

    rows: list[dict[str, Any]] = []
    for fixture, message in zip(fixtures, messages, strict=True):
        run_tier1_extraction_for_message(message.id)
        run_tier2_detail_fill_for_message(message.id)
        db = SessionLocal()
        try:
            refreshed = db.get(RawMessage, message.id)
            assert refreshed is not None
            actual = _actual_values(db, refreshed)
        finally:
            db.close()
        rows.append({"raw_id": fixture["raw_id"], "origin": fixture["origin"], "comparison": _compare(fixture["expected"], actual), "actual": actual})

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = REPORT_DIR / f"casualty_gold_eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    missing = sum(item["observed"] == "missing" for row in rows for item in row["comparison"])
    print(f"processed={len(rows)} expected_fields_missing={missing} report={report}")


if __name__ == "__main__":
    main()
