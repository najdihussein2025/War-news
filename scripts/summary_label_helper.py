"""Golden-fixture labeling helper for the summary parser.

Fixtures live under ``tests/fixtures/summaries/pending/`` (newly proposed, awaiting a
human edit) and ``tests/fixtures/summaries/approved/`` (what ``test_summary_golden.py``
checks exact equality against). This tool never writes an opinion of its own into
``approved/`` — it only proposes, in ``pending/``, what the *current* parser produces, so
a reviewer can see what changed and correct it before approving.

No database: like the parser modules themselves, this reads the static
``gazetteer_snapshot.json`` fixture, never a live session.

Usage (dev stack):
    docker compose ... exec backend python -m scripts.summary_label_helper --list
    docker compose ... exec backend python -m scripts.summary_label_helper --show 1115
    docker compose ... exec backend python -m scripts.summary_label_helper --approve 1115
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from app.news.services.summaries.gazetteer import GazetteerSnapshot
from app.news.services.summaries.headers import default_header_dictionary
from app.news.services.summaries.parser import ParseResult, parse_summary
from app.news.services.summaries.window import resolve_window

ROOT = Path("tests/fixtures/summaries")
PENDING_DIR = ROOT / "pending"
APPROVED_DIR = ROOT / "approved"
GAZETTEER_PATH = ROOT / "gazetteer_snapshot.json"
LEXICON_PATH = Path("app/core/llm_knowledge/terminology/summary_location_lexicon.yaml")


def _load_gazetteer() -> GazetteerSnapshot:
    return GazetteerSnapshot.from_dict(json.loads(GAZETTEER_PATH.read_text(encoding="utf-8")))


def _load_lexicon() -> dict:
    return yaml.safe_load(LEXICON_PATH.read_text(encoding="utf-8"))


def proposed_expected(raw_text: str, posted_at: datetime) -> dict[str, Any]:
    """The parser's current output in the fixture's "expected" shape."""
    gazetteer = _load_gazetteer()
    headers = default_header_dictionary()
    lexicon = _load_lexicon()
    window = resolve_window(raw_text, posted_at)
    result: ParseResult = parse_summary(raw_text, gazetteer, headers, lexicon, window.anchor_date)
    return {
        "window": {
            "start": window.start.isoformat(),
            "end": window.end.isoformat(),
            "rule": window.rule,
            "note": window.note,
        },
        "items": [
            {
                "condition_id": item.condition_id,
                "primary": item.primary_village.name_ar,
                "secondary": item.secondary_village.name_ar if item.secondary_village else None,
                "qualifiers": list(item.qualifiers),
                "reported_count": item.reported_count,
                "location_texts": list(item.location_texts),
                "event_time": item.event_time.isoformat() if item.event_time else None,
                "origin_text": item.origin_text,
                "status": item.status,
                "source_header": item.header_text,
                "condition_source": item.condition_source,
            }
            for item in result.items
        ],
        "residual": [
            {"kind": r.kind, "text": r.text, "section_header": r.section_header, "offsets": list(r.offsets)}
            for r in result.residual
        ],
        "disposition": result.disposition,
        "leftover_tokens": list(result.leftover_tokens),
        "out_of_scope_lines": list(result.out_of_scope_lines),
        "auto_acceptable": result.auto_acceptable,
    }


def list_pending() -> list[dict[str, Any]]:
    rows = []
    for path in sorted(PENDING_DIR.glob("*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        rows.append({"message_id": case["message_id"], "channel": case.get("channel"), "badge": case.get("badge"), "path": path})
    return rows


def _fixture_path(message_id: int) -> Path:
    for directory in (PENDING_DIR, APPROVED_DIR):
        path = directory / f"{message_id}.json"
        if path.exists():
            return path
    raise FileNotFoundError(f"No fixture for message_id={message_id} in pending/ or approved/.")


def show(message_id: int) -> None:
    path = _fixture_path(message_id)
    case = json.loads(path.read_text(encoding="utf-8"))
    print(f"=== message_id={message_id} ({path.parent.name}) ===")
    print(case["raw_text"])
    print()
    proposal = proposed_expected(case["raw_text"], datetime.fromisoformat(case["posted_at"]))
    case["expected"] = proposal
    case["status"] = "pending_review"
    path.write_text(json.dumps(case, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote the parser's current proposal to {path}. Edit 'expected' by hand, then re-run with --approve.")
    print(json.dumps(proposal, ensure_ascii=False, indent=2))


def approve(message_id: int) -> None:
    path = _fixture_path(message_id)
    case = json.loads(path.read_text(encoding="utf-8"))
    case["status"] = "approved"
    APPROVED_DIR.mkdir(parents=True, exist_ok=True)
    target = APPROVED_DIR / f"{message_id}.json"
    target.write_text(json.dumps(case, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if path != target:
        path.unlink()
    print(f"Approved: {target}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="List pending fixtures.")
    group.add_argument("--show", type=int, metavar="MESSAGE_ID", help="Print the text and write the parser's current proposal.")
    group.add_argument("--approve", type=int, metavar="MESSAGE_ID", help="Move an edited fixture from pending/ to approved/.")
    args = parser.parse_args()

    if args.list:
        rows = list_pending()
        print(f"{len(rows)} pending fixture(s):")
        for row in rows:
            print(f"  {row['message_id']}  channel={row['channel']!r}  badge={row['badge']!r}")
    elif args.show is not None:
        show(args.show)
    else:
        approve(args.approve)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
