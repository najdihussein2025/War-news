"""Read-only audit of every detected summary bulletin against same-window news.

Run from an image that has the application dependencies::

    python -m scripts.review_summaries_vs_news --since 2026-04-01 --until 2026-10-08

The script deliberately does not use intake_summary: that service persists rows.  It
uses its exact detection/parser/window guard in memory instead, and opens PostgreSQL
with ``default_transaction_read_only=on`` before performing any query.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import os
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# The deploy DB is intentionally selected before importing app.core.config, whose
# module-level settings object otherwise loads .env.
load_dotenv(".env.main", override=True)

from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.news.models import Condition, Incident, RawMessage, Village
from app.news.services.summaries.condition_families import ConditionFamilies, load_condition_families
from app.news.services.summaries.detection import detect_summary
from app.news.services.summaries.gazetteer import build_gazetteer_snapshot
from app.news.services.summaries.header_store import header_dictionary_for_session
from app.news.services.summaries.lexicon import LEXICON
from app.news.services.summaries.normalize import normalize_summary_text, normalize_token
from app.news.services.summaries.parser import parse_summary
from app.news.services.summaries.window import BEIRUT, resolve_window


@dataclass
class ParsedBulletin:
    raw: RawMessage
    channels: str
    member_ids: list[int]
    window_start: datetime
    window_end: datetime
    window_rule: str
    items: list
    unresolved_locations: list[str]
    unknown_headers: list[str]


def _fingerprint(value: str) -> str:
    return hashlib.sha256(" ".join(normalize_summary_text(value).text.split()).encode("utf-8")).hexdigest()


def _local_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(BEIRUT).replace(tzinfo=None)


def _incident_at(row: Incident) -> datetime:
    return datetime.combine(row.event_date, row.event_time or time.min)


def _fits(row: Incident, start: datetime, end: datetime, tolerance: int) -> bool:
    lower = _local_naive(start - timedelta(minutes=tolerance))
    upper = _local_naive(end + timedelta(minutes=tolerance))
    at = _incident_at(row)
    return lower <= at <= upper


def _accepted_parse(raw: RawMessage, gazetteer, headers):
    """The same detect + false-positive guard as intake_summary, without writes."""
    body = raw.raw_text or ""
    if not detect_summary(body).is_summary:
        return None
    posted = raw.message_datetime or raw.received_at
    window = resolve_window(body, posted)
    result = parse_summary(body, gazetteer, headers, LEXICON, window.anchor_date)
    recognized = [header for header in result.headers if header.status == "approved"]
    if len(result.items) + len(result.unresolved_places) < 2 or not recognized:
        return None
    return window, result


def _raw_in_window(rows: list[RawMessage], start: datetime, end: datetime) -> list[RawMessage]:
    lower, upper = _local_naive(start), _local_naive(end)
    return [row for row in rows if row.message_datetime and lower <= _local_naive(row.message_datetime) <= upper]


def _aliases(session: Session) -> dict[int, set[str]]:
    names: dict[int, set[str]] = defaultdict(set)
    for village_id, name in session.execute(select(Village.id, Village.ref_name_ar)):
        if name:
            names[village_id].add(normalize_token(name))
    for village_id, alias in session.execute(text("select village_id, alias_text from village_location_aliases where is_active")).all():
        if alias:
            names[village_id].add(normalize_token(alias))
    return names


def _mentions(raw: RawMessage, aliases: set[str]) -> bool:
    body = normalize_token(raw.raw_text or "")
    return any(alias and alias in body for alias in aliases)


def _status_reason(raw: RawMessage) -> str:
    result = raw.filter_result or raw.cnrs_classification or {}
    return str(result.get("reason") or result.get("verdict_reason") or raw.error_message or "unspecified")[:500]


def _incident_rows(session: Session, earliest: datetime, latest: datetime) -> list[Incident]:
    # One day either side retains date-only events that the live matcher accepts.
    return list(session.scalars(select(Incident).where(
        Incident.event_date >= _local_naive(earliest).date() - timedelta(days=1),
        Incident.event_date <= _local_naive(latest).date() + timedelta(days=1),
    )))


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", required=True, type=date.fromisoformat)
    parser.add_argument("--until", required=True, type=date.fromisoformat)
    parser.add_argument("--channel")
    args = parser.parse_args()
    if args.until < args.since:
        parser.error("--until must be on or after --since")

    # PostgreSQL refuses every mutation at the server, even if a future edit to
    # this script accidentally introduces one.  Do not use the application's
    # SessionLocal because its connection is not constrained this way.
    engine = create_engine(settings.database_url, connect_args={"options": "-c default_transaction_read_only=on"}, pool_pre_ping=True)
    @event.listens_for(engine, "connect")
    def _readonly(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
        cursor.close()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with Session() as session:
        readonly = session.execute(text("SHOW transaction_read_only")).scalar_one()
        print(f"read_only_transaction={readonly}")
        if str(readonly).lower() not in {"on", "true"}:
            raise RuntimeError("refusing to run: PostgreSQL transaction is not read-only")
        print("execution=local checkout with .env.main; parser/window/matcher code is present")

        begin = datetime.combine(args.since, time.min, tzinfo=BEIRUT)
        finish = datetime.combine(args.until + timedelta(days=1), time.min, tzinfo=BEIRUT)
        query = select(RawMessage).where(RawMessage.raw_text.is_not(None), RawMessage.message_datetime >= begin, RawMessage.message_datetime < finish)
        if args.channel:
            query = query.where(RawMessage.source_name == args.channel)
        raw_rows = list(session.scalars(query.order_by(RawMessage.message_datetime, RawMessage.id)))
        gazetteer, headers = build_gazetteer_snapshot(session), header_dictionary_for_session(session)
        accepted: list[tuple[RawMessage, object, object]] = []
        for raw in raw_rows:
            parsed = _accepted_parse(raw, gazetteer, headers)
            if parsed:
                accepted.append((raw, *parsed))

        groups: dict[str, list[tuple[RawMessage, object, object]]] = defaultdict(list)
        for candidate in accepted:
            groups[_fingerprint(candidate[0].raw_text or "")].append(candidate)
        bulletins: list[ParsedBulletin] = []
        for group in groups.values():
            group.sort(key=lambda entry: (entry[0].message_datetime or entry[0].received_at, entry[0].id))
            raw, window, result = group[0]
            channels = "; ".join(sorted({entry[0].source_name or "(unknown)" for entry in group}))
            bulletins.append(ParsedBulletin(raw, channels, [entry[0].id for entry in group], window.start, window.end, window.rule,
                list(result.items), list(result.unresolved_places), list(result.unresolved_headers)))

        earliest = min((bulletin.window_start for bulletin in bulletins), default=begin)
        latest = max((bulletin.window_end for bulletin in bulletins), default=finish)
        all_incidents = _incident_rows(session, earliest, latest)
        all_news = list(session.scalars(select(RawMessage).where(RawMessage.raw_text.is_not(None), RawMessage.message_datetime >= earliest - timedelta(hours=2), RawMessage.message_datetime <= latest + timedelta(hours=2))))
        families, aliases = load_condition_families(session), _aliases(session)
        condition_names = dict(session.execute(select(Condition.id, Condition.action_ar)).all())
        village_names = dict(session.execute(select(Village.id, Village.ref_name_ar)).all())
        summary_message_ids = {raw.id for raw, _, _ in accepted}
        item_rows: list[dict] = []
        old_rows: list[dict] = []
        unresolved_locations: Counter[str] = Counter(); unknown_headers: Counter[str] = Counter()

        for bulletin in bulletins:
            for value in bulletin.unresolved_locations: unresolved_locations[value] += 1
            for value in bulletin.unknown_headers: unknown_headers[value] += 1
            window_incidents = [row for row in all_incidents if _fits(row, bulletin.window_start, bulletin.window_end, settings.summary_match_tolerance_minutes)]
            live = [row for row in window_incidents if row.raw_message_id not in summary_message_ids and not row.is_deleted and row.verification_status != "rejected"]
            parsed_pairs: set[tuple[int, int]] = set()
            for item in bulletin.items:
                parsed_pairs.add((item.primary_village.id, item.condition_id))
                if item.secondary_village: parsed_pairs.add((item.secondary_village.id, item.condition_id))
                villages = {item.primary_village.id} | ({item.secondary_village.id} if item.secondary_village else set())
                same_village = [row for row in live if row.village_id in villages]
                matches = [row for row in same_village if families.same(item.condition_id, row.condition_id)]
                subreason = ""; detail = ""; matched_raw: list[str] = []
                if matches:
                    classification = "DUPLICATE_OF_NEWS"
                    minutes = min(round(((_local_naive(bulletin.raw.message_datetime or bulletin.raw.received_at) - _incident_at(row)).total_seconds()) / 60) for row in matches)
                elif same_village:
                    classification, minutes = "SAME_VILLAGE_OTHER_ACTION", ""
                    subreason = "; ".join(sorted({condition_names.get(row.condition_id, str(row.condition_id)) for row in same_village}))
                else:
                    classification, minutes = "NOT_IN_INCIDENTS", ""
                    candidate_news = [raw for raw in _raw_in_window(all_news, bulletin.window_start, bulletin.window_end) if raw.id not in summary_message_ids and _mentions(raw, aliases.get(item.primary_village.id, set()))]
                    rejected = [raw for raw in candidate_news if str(raw.status.value if hasattr(raw.status, "value") else raw.status) == "rejected"]
                    failed = [raw for raw in candidate_news if str(raw.status.value if hasattr(raw.status, "value") else raw.status) in {"pending", "error", "held_for_review"}]
                    wrong = [row for row in window_incidents if row.raw_message_id in {raw.id for raw in candidate_news} and row.village_id not in villages]
                    if rejected:
                        subreason, matched_raw = "NEWS_REJECTED", [str(raw.id) for raw in rejected]
                        detail = "; ".join(sorted({_status_reason(raw) for raw in rejected}))
                    elif failed:
                        subreason, matched_raw = "NEWS_FAILED", [str(raw.id) for raw in failed]
                        detail = "; ".join(sorted({str(raw.status.value if hasattr(raw.status, "value") else raw.status) for raw in failed}))
                    elif wrong:
                        subreason, matched_raw = "NEWS_WRONG_VILLAGE", [str(row.raw_message_id) for row in wrong if row.raw_message_id]
                        detail = "; ".join(sorted({str(village_names.get(row.village_id, row.village_id)) for row in wrong}))
                    else: subreason = "NEWS_NEVER_ARRIVED"
                item_rows.append({"summary_message_id": bulletin.raw.id, "channels": bulletin.channels, "date": (bulletin.raw.message_datetime or bulletin.raw.received_at).date(), "window_start": bulletin.window_start, "window_end": bulletin.window_end, "header": item.header_text, "condition": condition_names.get(item.condition_id, item.condition_id), "location_text": " | ".join(item.location_texts), "village_id": item.primary_village.id, "village_name": item.primary_village.name_ar, "modifier": "between" if item.secondary_village else "none", "count": item.reported_count, "classification": classification, "sub_reason": subreason, "detail": detail, "matched_incident_ids": ";".join(str(row.id) for row in matches if matches), "matched_raw_message_ids": ";".join(matched_raw), "minutes_between_news_and_summary": minutes})

            for row in [entry for entry in window_incidents if entry.raw_message_id in bulletin.member_ids]:
                matches = [entry for entry in live if entry.id != row.id and entry.village_id == row.village_id and families.same(row.condition_id, entry.condition_id)]
                if matches: old_class, duplicate = "DUPLICATE_ROW", str(matches[0].id)
                elif (row.village_id, row.condition_id) in parsed_pairs: old_class, duplicate = "UNIQUE_CORRECT", ""
                else: old_class, duplicate = "WRONG_ROW", ""
                old_rows.append({"incident_id": row.id, "summary_message_id": row.raw_message_id, "village": village_names.get(row.village_id, row.village_id), "condition": condition_names.get(row.condition_id, row.condition_id), "classification": old_class, "duplicate_of_incident_id": duplicate, "soft_deleted": row.is_deleted})

    # Files are intentionally written only after the database session has closed.
    output = Path("Docs/audits") / f"summary_vs_news_review_{date.today().isoformat()}"
    output.mkdir(parents=True, exist_ok=True)
    fields = ["summary_message_id", "channels", "date", "window_start", "window_end", "header", "condition", "location_text", "village_id", "village_name", "modifier", "count", "classification", "sub_reason", "detail", "matched_incident_ids", "matched_raw_message_ids", "minutes_between_news_and_summary"]
    _write_csv(output / "items.csv", fields, item_rows)
    _write_csv(output / "old_rows.csv", ["incident_id", "summary_message_id", "village", "condition", "classification", "duplicate_of_incident_id", "soft_deleted"], old_rows)
    by_class = Counter(row["classification"] for row in item_rows); by_reason = Counter(row["sub_reason"] for row in item_rows if row["sub_reason"].startswith("NEWS_")); old_counts = Counter(row["classification"] for row in old_rows)
    total = len(item_rows) or 1
    coverage_by_channel: dict[str, list[dict]] = defaultdict(list)
    for row in item_rows:
        for channel in row["channels"].split("; "): coverage_by_channel[channel].append(row)
    month = defaultdict(list)
    for row in item_rows: month[str(row["date"])[:7]].append(row)
    missing_villages = Counter(row["village_name"] for row in item_rows if row["classification"] == "NOT_IN_INCIDENTS")
    rejected_reasons = Counter(); wrong_pairs = Counter()
    for row in item_rows:
        if row["sub_reason"] == "NEWS_REJECTED": rejected_reasons[row["detail"] or "unspecified"] += 1
        if row["sub_reason"] == "NEWS_WRONG_VILLAGE": wrong_pairs[(row["village_name"], row["detail"] or "unknown")] += 1
    def pct(value: int, denom: int = total) -> str: return f"{100 * value / (denom or 1):.1f}%"
    lines = [f"# Summary vs. news review — {date.today().isoformat()}", "", f"Range: {args.since} through {args.until}. Read-only audit; grouped exact normalized reposts.", "", "## Headline numbers", "", f"- Summaries reviewed: {len(bulletins)}", f"- Reposts grouped: {sum(len(b.member_ids) - 1 for b in bulletins)}", f"- Total items: {len(item_rows)}", f"- DUPLICATE_OF_NEWS: {by_class['DUPLICATE_OF_NEWS']} ({pct(by_class['DUPLICATE_OF_NEWS'])})", f"- SAME_VILLAGE_OTHER_ACTION: {by_class['SAME_VILLAGE_OTHER_ACTION']} ({pct(by_class['SAME_VILLAGE_OTHER_ACTION'])})", f"- NOT_IN_INCIDENTS: {by_class['NOT_IN_INCIDENTS']} ({pct(by_class['NOT_IN_INCIDENTS'])})", *[f"  - {reason}: {count}" for reason, count in sorted(by_reason.items())], "", "## Double counting today", "", f"- Incident rows created from summaries: {len(old_rows)}", f"- DUPLICATE_ROW: {old_counts['DUPLICATE_ROW']}", f"- UNIQUE_CORRECT: {old_counts['UNIQUE_CORRECT']}", f"- WRONG_ROW: {old_counts['WRONG_ROW']}", "", "## By channel", ""]
    lines += [f"- {channel}: {pct(sum(r['classification'] == 'DUPLICATE_OF_NEWS' for r in rows), len(rows))} already covered ({len(rows)} items)" for channel, rows in sorted(coverage_by_channel.items())]
    lines += ["", "## By month", "", "| month | items | duplicate | same village / other action | not in incidents |", "|---|---:|---:|---:|---:|"]
    lines += [f"| {key} | {len(rows)} | {sum(r['classification']=='DUPLICATE_OF_NEWS' for r in rows)} | {sum(r['classification']=='SAME_VILLAGE_OTHER_ACTION' for r in rows)} | {sum(r['classification']=='NOT_IN_INCIDENTS' for r in rows)} |" for key, rows in sorted(month.items())]
    for heading, values in [("Top 20 villages summaries list but news missed", missing_villages), ("Top 20 NEWS_REJECTED reasons", rejected_reasons), ("Top unresolved locations", unresolved_locations), ("Top unknown headers", unknown_headers), ("NEWS_WRONG_VILLAGE pairs (summary village → recorded village)", wrong_pairs)]:
        lines += ["", f"## {heading}", ""] + [f"- {key}: {count}" for key, count in values.most_common(20)]
    ranked_duplicates = sorted(bulletins, key=lambda b: sum(r['summary_message_id'] == b.raw.id and r['classification'] == 'DUPLICATE_OF_NEWS' for r in item_rows), reverse=True)[:5]
    ranked_missing = sorted(bulletins, key=lambda b: sum(r['summary_message_id'] == b.raw.id and r['classification'] == 'NOT_IN_INCIDENTS' for r in item_rows), reverse=True)[:5]
    random.seed(0); examples = ranked_duplicates + ranked_missing + random.sample(bulletins, min(5, len(bulletins)))
    lines += ["", "## 15 example summaries", ""]
    for bulletin in examples:
        lines += [f"### Summary {bulletin.raw.id}", "", f"Channel: {bulletin.channels}; date: {(bulletin.raw.message_datetime or bulletin.raw.received_at).isoformat()}; window: {bulletin.window_start.isoformat()} → {bulletin.window_end.isoformat()}", "", (bulletin.raw.raw_text or "")[:300], "", "| village | condition | classification | incident ids / raw ids |", "|---|---|---|---|"]
        lines += [f"| {row['village_name']} | {row['condition']} | {row['classification']} {row['sub_reason']} | {row['matched_incident_ids'] or row['matched_raw_message_ids']} |" for row in item_rows if row['summary_message_id'] == bulletin.raw.id]
        lines.append("")
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"summaries_reviewed={len(bulletins)} reposts_grouped={sum(len(b.member_ids)-1 for b in bulletins)} total_items={len(item_rows)}")
    print(f"duplicate_of_news={by_class['DUPLICATE_OF_NEWS']} same_village_other_action={by_class['SAME_VILLAGE_OTHER_ACTION']} not_in_incidents={by_class['NOT_IN_INCIDENTS']} reasons={dict(by_reason)}")
    print(f"double_counting summary_rows={len(old_rows)} duplicate_row={old_counts['DUPLICATE_ROW']} unique_correct={old_counts['UNIQUE_CORRECT']} wrong_row={old_counts['WRONG_ROW']}")
    print(f"report={output / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
