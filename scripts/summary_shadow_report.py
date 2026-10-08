"""Read-only shadow report: summary-flow proposals vs. what the old path produced.

For every shadow-mode summary in a date range (one whose ``shadow_result`` was filled by
the reconcile worker's dry run), this reports what the summary flow *would* have done and
compares it with the incidents Tier 1 actually materialized from the same raw message —
this is the evidence for ``RUNBOOK.md``'s go-live checklist. It writes nothing to the
database; ``reprocess_summaries.classify_old_incidents`` does the comparison.

Usage (dev stack):
    docker compose ... exec backend python -m scripts.summary_shadow_report --since 2026-10-06 --until 2026-10-08
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from app.core.database import SessionLocal
from app.news.models import RawMessage
from app.news.models.summary_bulletin import SummaryBulletin, SummaryItem, SummaryReviewTask
from app.news.services.summaries.condition_families import load_condition_families
from scripts.reprocess_summaries import classify_old_incidents


def shadow_summaries(session, since: date, until: date) -> list[SummaryBulletin]:
    return list(
        session.scalars(
            select(SummaryBulletin)
            .where(
                SummaryBulletin.shadow_result.is_not(None),
                SummaryBulletin.created_at >= datetime.combine(since, datetime.min.time(), tzinfo=timezone.utc),
                SummaryBulletin.created_at < datetime.combine(until, datetime.min.time(), tzinfo=timezone.utc) + timedelta(days=1),
            )
            .order_by(SummaryBulletin.created_at.asc())
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", required=True, type=date.fromisoformat)
    parser.add_argument("--until", required=True, type=date.fromisoformat)
    args = parser.parse_args()

    totals = {"matched": 0, "would_create": 0, "review": 0, "skipped": 0}
    open_tasks = 0
    per_summary: list[str] = []
    old_path_wrong = 0
    old_path_duplicate = 0

    with SessionLocal() as session:
        summaries = shadow_summaries(session, args.since, args.until)
        families = load_condition_families(session)
        for summary in summaries:
            shadow = summary.shadow_result or {}
            counts = shadow.get("counts", {})
            for key in totals:
                totals[key] += counts.get(key, 0)
            task = session.scalar(select(SummaryReviewTask).where(SummaryReviewTask.summary_id == summary.id))
            if task is not None and task.status.value == "open":
                open_tasks += 1

            parsed_items = list(session.scalars(select(SummaryItem).where(SummaryItem.summary_id == summary.id)))
            raw_message = session.get(RawMessage, summary.raw_message_id)
            old_rows = classify_old_incidents(session, raw_message, parsed_items, families) if raw_message is not None else []
            wrong = sum(1 for r in old_rows if r.classification == "wrong")
            dup = sum(1 for r in old_rows if r.classification == "duplicate_of_live")
            old_path_wrong += wrong
            old_path_duplicate += dup

            per_summary.append(
                f"| {summary.id} | {summary.channel or ''} | {shadow.get('counts', {})} | "
                f"{'open' if task and task.status.value == 'open' else 'none'} | {wrong} | {dup} |"
            )

    today = date.today().isoformat()
    docs_dir = Path("Docs/audits")
    docs_dir.mkdir(parents=True, exist_ok=True)
    out_path = docs_dir / f"summary_shadow_report_{today}.md"
    lines = [
        f"# Summary shadow report — {today}",
        "",
        f"Range: {args.since.isoformat()} to {args.until.isoformat()}. Summaries in shadow mode: {len(summaries)}.",
        "",
        "## Totals across all summaries",
        "",
        f"- matched: {totals['matched']}",
        f"- would_create: {totals['would_create']}",
        f"- review (unresolved/unknown/casualty): {totals['review']}",
        f"- open review tasks: {open_tasks}",
        f"- old-path rows that look wrong: {old_path_wrong}",
        f"- old-path rows that duplicate a live incident: {old_path_duplicate}",
        "",
        "## Per-summary diff",
        "",
        "| summary_id | channel | shadow counts | review task | old-path wrong | old-path duplicate |",
        "|---|---|---|---|---|---|",
        *per_summary,
    ]
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Summary shadow report: {len(summaries)} summaries, {open_tasks} open review tasks.")
    print(f"Report: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
