"""Rollback-by-default casualty validation and repair report."""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.news.models  # noqa: F401
import app.sources.models  # noqa: F401
from app.core.database import SessionLocal
from app.news.models import Incident, IncidentDetail, IncidentUpdate, RawMessage, UpdateAction, Village
from app.news.models.bulletin_casualty_group import CasualtyScope
from app.news.repositories.bulletin_casualty_group_repository import BulletinCasualtyGroupRepository
from app.news.services.incident_details.incident_casualty_recompute import (
    DETAIL_FIELDS, INCIDENT_FIELDS, connected_casualty_sources,
    recompute_incident_casualties, resolve_casualty_selection,
    validate_incident_casualty_sources, village_mentions, _qualifier_catalog,
    _requires_location_context, _village_catalog, _claim_units,
)
from app.core.llm_knowledge.message_text import clean_message_text
from app.news.services.incident_details.casualty_text import (
    find_count_mentions, find_explicit_none, find_supporting_mention,
    has_casualty_wording, strike_list_number_spans, strip_page_header,
)
from app.core.text_normalization import normalize_arabic_text

CLASSES = ("corrected", "unchanged", "needs_reextraction", "source_missing", "village_mismatch", "bulletin_aggregate", "conflict_flagged", "approximate_flagged", "needs_business_decision", "skipped_admin_edited")
PROVEN_MANIFEST = Path("Docs/recon/casualty_proven_cases.json")
PREVIOUS_REPORT_DIR = Path("Docs/repair/round5")
_NON_LEBANESE_VICTIM_RE = re.compile(
    r"(?:اصابه|إصابة|مقتل|قتل|جرح)\s+(?:\w+\s+){0,3}(?:جنود?|ضباط?|جندي)\s+(?:العدو|الاسرائيلي)|"
    r"(?:جنود?|ضباط?)\s+(?:العدو|الاسرائيلي)(?:\s+\w+){0,3}\s+(?:اصيبوا|قتلوا|جرحوا)|"
    r"نقل\s+(?:\w+\s+){0,5}(?:الي|إلى)\s+مستشفي\s+رامبام|مقتل\s+جندي\s+اسرائيلي",
    re.IGNORECASE,
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--incident", action="append", default=[])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--reextract", action="store_true")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--output-dir", type=Path, default=Path("Docs/repair"))
    return parser.parse_args()


def _admin_edited(db: Any, incident: Incident) -> bool:
    values = db.scalars(select(IncidentUpdate.new_values).where(IncidentUpdate.incident_id == incident.id, IncidentUpdate.action == UpdateAction.edit, IncidentUpdate.performed_by.is_not(None))).all()
    casualty_keys = set(INCIDENT_FIELDS) | {f"detail.{key}" for key in DETAIL_FIELDS}
    return any(isinstance(value, dict) and set(value) & casualty_keys for value in values)


def _admin_edit_info(db: Any, incident: Incident) -> list[dict[str, Any]]:
    updates = db.scalars(select(IncidentUpdate).where(
        IncidentUpdate.incident_id == incident.id,
        IncidentUpdate.action == UpdateAction.edit,
        IncidentUpdate.performed_by.is_not(None),
    ).order_by(IncidentUpdate.created_at.asc())).all()
    return [
        {"editor_id": str(update.performed_by), "at": str(update.created_at), "values": update.new_values or {}}
        for update in updates
    ]


def _candidate_query(args: argparse.Namespace):
    query = select(Incident).outerjoin(IncidentDetail, IncidentDetail.incident_id == Incident.id).where(Incident.is_deleted.is_(False))
    if args.incident:
        return query.where(Incident.id.in_([UUID(value) for value in args.incident]))
    if args.all:
        return query
    return query.where(or_(Incident.deaths.is_not(None), Incident.injuries.is_not(None), Incident.total_deaths.is_not(None), Incident.total_injuries.is_not(None), Incident.casualty_status.is_not(None), *(getattr(IncidentDetail, key).is_not(None) for key in DETAIL_FIELDS)))


def _state(incident: Incident, detail: IncidentDetail | None) -> dict[str, int | None]:
    values = {key: getattr(incident, key, None) for key in INCIDENT_FIELDS}
    values.update({f"detail.{key}": getattr(detail, key, None) if detail else None for key in DETAIL_FIELDS})
    return values


def _priority_ids() -> dict[str, int]:
    if not PROVEN_MANIFEST.exists():
        return {}
    data = json.loads(PROVEN_MANIFEST.read_text(encoding="utf-8"))
    return {str(value): index for index, value in enumerate(data.get("incident_ids", []))}


def _reason_for_change(old: dict[str, Any], new: dict[str, Any]) -> str:
    changes = [f"{key}: {old.get(key)} -> {new.get(key)}" for key in old if old.get(key) != new.get(key)]
    if all(new.get(key) is None for key in new):
        return "unsupported stored casualty values cleared by deterministic source validation"
    return "; ".join(changes) or "source-validated values already match"


def _previous_rows() -> dict[str, dict[str, str]]:
    reports = sorted(PREVIOUS_REPORT_DIR.glob("casualty_repair_*.csv"))
    if not reports:
        return {}
    with reports[-1].open(encoding="utf-8-sig", newline="") as handle:
        return {row["incident_id"]: row for row in csv.DictReader(handle)}


def _is_non_lebanese_casualty_case(sources: list[Any]) -> bool:
    return any(_NON_LEBANESE_VICTIM_RE.search(normalize_arabic_text(text)) for source in sources if (text := clean_message_text(source.text)))


def _non_lebanese_note(sources: list[Any]) -> str:
    for source in sources:
        cleaned = strip_page_header(clean_message_text(source.text))
        if not _NON_LEBANESE_VICTIM_RE.search(normalize_arabic_text(cleaned)):
            continue
        mention = next((item for item in find_count_mentions(cleaned) if item.counts_total), None)
        if mention is not None:
            return f"إصابة {mention.value} من جنود العدو (غير محتسبة)"
    return "ضحايا من جنود العدو (غير محتسبة)"


def _related_shared_toll(
    db: Any, incident: Incident, old: dict[str, Any], aliases: list[tuple[str, int, str]],
    qualifier_names: frozenset[str],
) -> tuple[list[Any], list[str]]:
    """Find an exact same-day/same-village toll retained on a sibling incident."""
    deaths, injuries = old.get("deaths"), old.get("injuries")
    if not isinstance(deaths, int) and not isinstance(injuries, int):
        return [], []
    siblings = db.scalars(select(Incident).where(
        Incident.id != incident.id,
        Incident.event_date == incident.event_date,
        Incident.village_id == incident.village_id,
        Incident.is_deleted.is_(False),
    )).all()
    found_sources: list[Any] = []
    quotes: list[str] = []
    for sibling in siblings:
        for source in connected_casualty_sources(db, sibling):
            cleaned = strip_page_header(clean_message_text(source.text))
            for mention in find_count_mentions(cleaned):
                if not mention.kind or not mention.counts_total:
                    continue
                clause = _claim_clause_for_report(cleaned, mention.text)
                if len({item[2] for item in village_mentions(clause, aliases, qualifier_names)}) <= 1:
                    continue
                counts = {(item.kind, item.value) for item in find_count_mentions(clause) if item.kind and item.counts_total}
                if ((not isinstance(deaths, int) or ("deaths", deaths) in counts)
                        and (not isinstance(injuries, int) or ("injuries", injuries) in counts)):
                    found_sources.append(source)
                    quotes.append(clause)
    unique_sources = {source.raw_message_id: source for source in found_sources}
    return list(unique_sources.values()), list(dict.fromkeys(quotes))


def _claim_clause_for_report(text: str, quote: str) -> str:
    """Small report-side equivalent: keep the bullet/line containing a mention."""
    at = text.find(quote)
    if at < 0:
        return quote
    start = max(text.rfind("\n", 0, at), text.rfind("•", 0, at)) + 1
    ends = [pos for pos in (text.find("\n", at), text.find("•", at)) if pos >= 0]
    end = min(ends) if ends else len(text)
    return text[start:end].strip()[:300]


def _lowered_fields(old: dict[str, Any], new: dict[str, Any]) -> list[tuple[str, int]]:
    return [
        (key, value) for key, value in old.items()
        if isinstance(value, int) and (new.get(key) is None or (isinstance(new.get(key), int) and new[key] < value))
    ]


def _disproof(
    old: dict[str, Any], new: dict[str, Any], sources: list[Any], validation: Any,
    incident_village_id: int | None,
) -> tuple[str | None, str]:
    """Return only positive, reviewable proof that a stored value is wrong."""
    lowered = _lowered_fields(old, new)
    if not lowered:
        return None, ""
    if validation.aggregate_quotes:
        return "shared_toll", validation.aggregate_quotes[0]
    other = [claim for claim in validation.claims if claim.village_id != incident_village_id]
    if other and not any(claim.village_id == incident_village_id for claim in validation.claims):
        return "belongs_to_other_village", next(iter(other[0].quotes.values()), other[0].village_name)
    cleaned_sources = [strip_page_header(clean_message_text(source.text)) for source in sources]
    for key, value in lowered:
        kind = "injuries" if key.endswith(("injuries", "_i")) else "deaths"
        for text in cleaned_sources:
            explicit = find_explicit_none(text, kind)
            if value == 0 and explicit:
                return "explicit_no_casualties", explicit
            for span in strike_list_number_spans(text):
                if re.search(rf"(?<!\d){value}(?!\d)", span):
                    return "strike_count", span
            subset = re.search(rf"(?:من\s+بينهم|بينهم|منهم)\s+{value}(?!\d)[^،.\n]{{0,80}}", normalize_arabic_text(text))
            if subset:
                return "subset_count", subset.group(0).strip()
        if key.startswith("detail."):
            phrase = next((text[:300] for text in cleaned_sources if has_casualty_wording(text, kind)), "grammar-only demographic value")
            return "grammar_only_demographic", phrase
        for source, cleaned in zip(sources, cleaned_sources):
            original = clean_message_text(source.text)
            if find_supporting_mention(original, kind, value) and not find_supporting_mention(cleaned, kind, value):
                return "byline_or_header", original[:300]
        for text in cleaned_sources:
            number = re.search(rf".{{0,60}}(?<!\d){value}(?!\d).{{0,60}}", text)
            if number and find_supporting_mention(number.group(0), kind, value) is None:
                return "no_casualty_word_near_number", number.group(0).strip()
    return None, ""


def _store_aggregate_groups(
    db: Any,
    sources: list[Any],
    aggregate_quotes: tuple[str, ...],
    aliases: list[tuple[str, int, str]],
    qualifier_names: frozenset[str],
) -> list[str]:
    """Create reviewable aggregate ownership in the same transaction as repair."""
    stored: list[str] = []
    repository = BulletinCasualtyGroupRepository(db)
    for quote in aggregate_quotes:
        source = next(
            (
                item for item in sources
                if quote in strip_page_header(clean_message_text(item.text))
            ),
            None,
        )
        if source is None:
            continue
        mentions = [item for item in find_count_mentions(quote) if item.kind and item.counts_total]
        deaths = [item.value for item in mentions if item.kind == "deaths"]
        injuries = [item.value for item in mentions if item.kind == "injuries"]
        village_ids = sorted({item[2] for item in village_mentions(quote, aliases, qualifier_names)})
        if not village_ids:
            cleaned_source = strip_page_header(clean_message_text(source.text))
            village_ids = sorted({item[2] for item in village_mentions(cleaned_source, aliases, qualifier_names)})
        if not village_ids and source.match_result:
            village_ids = sorted({
                item.get("matched_village_id")
                for item in source.match_result.get("village_matches", [])
                if isinstance(item.get("matched_village_id"), int)
                and item.get("village_role", "target") == "target"
            })
        if not village_ids or not (deaths or injuries):
            continue
        live = source.origin == "raw_messages" and db.get(RawMessage, source.raw_message_id) is not None
        if not live:
            stored.append(f"merged_from_snapshot raw {source.raw_message_id}: villages {village_ids}, deaths {max(deaths) if deaths else None}, injuries {max(injuries) if injuries else None}; stored in repair audit payload")
            continue
        repository.create_for_message(
            raw_message_id=source.raw_message_id,
            village_ids=village_ids,
            casualty_scope=CasualtyScope.bulletin_aggregate,
            total_deaths=max(deaths) if deaths else None,
            total_injuries=max(injuries) if injuries else None,
            created_at=source.received_at,
        )
        stored.append(f"raw {source.raw_message_id}: villages {village_ids}, deaths {max(deaths) if deaths else None}, injuries {max(injuries) if injuries else None}")
    return list(dict.fromkeys(stored))


def _excerpt(text: str, limit: int = 500) -> str:
    cleaned = strip_page_header(clean_message_text(text)).strip()
    return cleaned if len(cleaned) <= limit else cleaned[:limit].rstrip() + "…"


def main() -> int:
    args = _args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    md_path, csv_path = args.output_dir / f"casualty_repair_{stamp}.md", args.output_dir / f"casualty_repair_{stamp}.csv"
    counts = {name: 0 for name in CLASSES}
    rows: list[dict[str, Any]] = []
    failed = 0
    db = SessionLocal()
    try:
        aliases = _village_catalog(db)
        qualifier_names = _qualifier_catalog(db)
        candidates = list(db.scalars(_candidate_query(args)).unique())
        priority = _priority_ids()
        candidates.sort(key=lambda item: (priority.get(str(item.id), len(priority)), str(item.id)))
        for incident in candidates:
            try:
                detail = db.get(IncidentDetail, incident.id)
                old = _state(incident, detail)
                sources = connected_casualty_sources(db, incident)
                validation = validate_incident_casualty_sources(db, incident)
                if not validation.aggregate_quotes and not validation.claims:
                    related_sources, related_quotes = _related_shared_toll(db, incident, old, aliases, qualifier_names)
                    if related_quotes:
                        sources = list({source.raw_message_id: source for source in [*sources, *related_sources]}.values())
                        validation = replace(validation, aggregate_quotes=tuple(related_quotes))
                proposed, conflict, chosen_claims = resolve_casualty_selection(validation, incident.village_id)
                own_claims = [claim for claim in validation.claims if claim.village_id == incident.village_id]
                has_old_values = any(value is not None for value in old.values())
                changed = False
                aggregate_storage: list[str] = []
                disproof_code, disproving_text = _disproof(old, proposed, sources, validation, incident.village_id)
                audit_values: dict[str, Any] = {}
                admin_edit_info = _admin_edit_info(db, incident)
                if chosen_claims:
                    audit_values["chosen_casualty_claims"] = chosen_claims
                if _admin_edited(db, incident):
                    classification, reason = "skipped_admin_edited", "human casualty edit is authoritative"
                elif _is_non_lebanese_casualty_case(sources):
                    note = _non_lebanese_note(sources)
                    excluded = replace(validation, claims=(), aggregate_quotes=(), approximate_quotes=())
                    audit_values = {"non_lebanese_casualties_excluded": note}
                    changed = recompute_incident_casualties(db, incident, reason_code="repair", validation=excluded, audit_values=audit_values)
                    if incident.note_extra != note:
                        incident.note_extra = note
                        changed = True
                    classification, reason = "corrected", note
                elif validation.sources_with_text == 0:
                    classification, reason = "source_missing", "no connected live or archived source text"
                elif validation.claims and not own_claims:
                    removed = {key: value for key, value in old.items() if value is not None}
                    audit_values = {"mismatch_owner_villages": list(validation.attributed_villages), "removed_casualty_values": removed}
                    changed = recompute_incident_casualties(db, incident, reason_code="repair", validation=validation, audit_values=audit_values)
                    classification = "village_mismatch"
                    reason = incident.verification_reason or "source casualty claims belong to other villages"
                elif validation.aggregate_quotes and not own_claims:
                    aggregate_storage = _store_aggregate_groups(db, sources, validation.aggregate_quotes, aliases, qualifier_names)
                    if aggregate_storage:
                        audit_values = {"bulletin_aggregate_storage": aggregate_storage, "bulletin_aggregate_evidence": list(validation.aggregate_quotes)}
                        changed = recompute_incident_casualties(db, incident, reason_code="repair", validation=validation, audit_values=audit_values)
                        classification = "bulletin_aggregate"
                        reason = "shared or regional toll moved from the village row to a reviewable bulletin casualty group"
                    else:
                        classification = "needs_reextraction"
                        reason = "aggregate toll was not cleared because no live raw source could own a bulletin casualty group"
                elif validation.approximate_quotes:
                    audit_values = {"approximate_casualty_evidence": list(validation.approximate_quotes)}
                    changed = recompute_incident_casualties(db, incident, reason_code="repair", validation=validation, audit_values=audit_values)
                    classification = "approximate_flagged"
                    reason = "approximate casualty count requires manual verification: " + " | ".join(validation.approximate_quotes)
                elif own_claims:
                    if _lowered_fields(old, proposed) and disproof_code is None:
                        classification, reason = "needs_reextraction", "proposed lowering has no positive disproof; stored values left unchanged"
                    else:
                        if disproof_code:
                            audit_values.update({"disproof_code": disproof_code, "disproving_text": disproving_text})
                        changed = recompute_incident_casualties(db, incident, reason_code="repair", validation=validation, audit_values=audit_values)
                        classification = "conflict_flagged" if conflict else "corrected" if changed else "unchanged"
                        reason = conflict or _reason_for_change(old, _state(incident, detail))
                elif has_old_values and validation.disproved_sources:
                    if disproof_code is None:
                        classification, reason = "needs_reextraction", "source validation rejected stored values but produced no positive disproof"
                    else:
                        audit_values.update({"disproof_code": disproof_code, "disproving_text": disproving_text})
                        changed = recompute_incident_casualties(db, incident, reason_code="repair", validation=validation, audit_values=audit_values)
                        classification, reason = "corrected", f"{disproof_code}: {disproving_text}"
                elif has_old_values:
                    classification, reason = "needs_reextraction", "source text exists but no source yields an evidence-grounded village claim"
                else:
                    classification, reason = "unchanged", "no stored or source-supported casualty values"
                new = _state(incident, detail) if changed or classification in ("unchanged", "village_mismatch", "bulletin_aggregate", "conflict_flagged", "corrected") else old
                counts[classification] += 1
                village = db.get(Village, incident.village_id) if incident.village_id else None
                quotes = [f"{claim.village_name}: {quote}" for claim in validation.claims for quote in claim.quotes.values()]
                quote_villages: dict[str, set[int]] = defaultdict(set)
                for claim in validation.claims:
                    for quote in claim.quotes.values():
                        quote_villages[quote].add(claim.village_id)
                duplicate_quote_violations = sum(
                    len(village_ids) > len({item[2] for item in village_mentions(quote, aliases, qualifier_names)})
                    for quote, village_ids in quote_villages.items() if len(village_ids) > 1
                )
                aggregate_excerpts = [
                    _excerpt(source.text) for source in sources
                    if any(quote in strip_page_header(clean_message_text(source.text)) for quote in validation.aggregate_quotes)
                ]
                rows.append({
                    "incident_id": str(incident.id), "village": getattr(village, "ref_name_en", None) or incident.village_display_name or "", "date": str(incident.event_date),
                    "current": json.dumps(old, ensure_ascii=False), "proposed": json.dumps(new, ensure_ascii=False), "classification": classification, "reason": reason,
                    "attributed_villages": "; ".join(validation.attributed_villages), "source_ids": "; ".join(f"{s.raw_message_id}:{s.origin}" for s in sources), "evidence_quotes": " | ".join(dict.fromkeys(quotes)),
                    "aggregate_quotes": " | ".join(validation.aggregate_quotes), "aggregate_source_text": " | ".join(dict.fromkeys(aggregate_excerpts)),
                    "aggregate_storage": " | ".join(aggregate_storage),
                    "whole_token_violations": 0, "duplicate_quote_violations": duplicate_quote_violations,
                    "source_has_casualty_word": any(has_casualty_wording(source.text, kind) for source in sources for kind in ("deaths", "injuries")),
                    "source_excerpt": " | ".join(dict.fromkeys(_excerpt(source.text, 300) for source in sources))[:300],
                    "needs_business_decision": classification == "needs_business_decision",
                    "disproof_code": disproof_code or "", "disproving_text": disproving_text,
                    "audit_payload": json.dumps(audit_values, ensure_ascii=False),
                    "note_extra": incident.note_extra or "",
                    "chosen_claims": json.dumps(chosen_claims, ensure_ascii=False),
                    "admin_edit_info": json.dumps(admin_edit_info, ensure_ascii=False),
                })
                if args.apply:
                    db.commit()
                else:
                    db.rollback()
            except Exception as exc:
                db.rollback(); failed += 1
                rows.append({"incident_id": str(incident.id), "village": "", "date": str(incident.event_date), "current": "", "proposed": "", "classification": "failed", "reason": str(exc), "attributed_villages": "", "source_ids": "", "evidence_quotes": "", "aggregate_quotes": "", "aggregate_source_text": "", "aggregate_storage": "", "whole_token_violations": "", "duplicate_quote_violations": "", "source_has_casualty_word": "", "source_excerpt": "", "needs_business_decision": "", "disproof_code": "", "disproving_text": "", "audit_payload": "", "note_extra": "", "chosen_claims": "", "admin_edit_info": ""})
        if args.reextract:
            print("needs_reextraction ids (no automatic requeue mechanism found):")
            print("\n".join(row["incident_id"] for row in rows if row["classification"] == "needs_reextraction"))
    finally:
        if not args.apply:
            db.rollback()
        db.close()
    fields = list(rows[0]) if rows else ["incident_id"]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
    lines = ["# Casualty repair dry-run" if not args.apply else "# Casualty repair apply report", "", f"Generated: {stamp}", "", "## Summary", ""]
    cell = lambda value: str(value).replace("|", "\\|").replace("\n", " ")
    lines.extend(f"- {name}: {counts[name]}" for name in CLASSES)
    lines += [f"- failed: {failed}", f"- non-whole-token attributions: {sum(int(row.get('whole_token_violations') or 0) for row in rows)}", f"- duplicate-quote attribution violations: {sum(int(row.get('duplicate_quote_violations') or 0) for row in rows)}"]
    field_changes = {field: Counter() for field in (*INCIDENT_FIELDS, *(f"detail.{field}" for field in DETAIL_FIELDS))}
    invariant_rows = []
    demographic_rows = []
    sum_listed_rows = []
    for row in rows:
        if not row.get("current") or not row.get("proposed"):
            continue
        old, new = json.loads(row["current"]), json.loads(row["proposed"])
        for field in field_changes:
            before, after = old.get(field), new.get(field)
            if before == after:
                continue
            direction = "cleared" if before is not None and after is None else "filled" if before is None and after is not None else "up" if after > before else "down"
            field_changes[field][direction] += 1
            if field.startswith("detail."):
                demographic_rows.append((row, field, before, after))
        for base, total, details in (("deaths", "total_deaths", ("detail.male_d", "detail.female_d", "detail.children_d")), ("injuries", "total_injuries", ("detail.male_i", "detail.female_i", "detail.children_i"))):
            listed = sum(new.get(field) or 0 for field in details)
            if row["classification"] != "skipped_admin_edited" and ((new.get(total) is None) != (new.get(base) is None) or (new.get(total) is None and listed) or (new.get(total) is not None and new[total] < listed) or any(isinstance(new.get(field), int) and new[field] < 0 for field in (base, total, *details))):
                invariant_rows.append((row["incident_id"], base))
            if old.get(base) is None and new.get(base) is not None and listed == new.get(base):
                sum_listed_rows.append(row)
    lines += [f"- invariant violations: {len(invariant_rows)}"]
    lines += ["", "## Per-field change table", "", "| Field | Up | Down | Cleared | Filled |", "|---|---:|---:|---:|---:|"]
    for field, changes in field_changes.items():
        lines.append(f"| {field} | {changes['up']} | {changes['down']} | {changes['cleared']} | {changes['filled']} |")
    lines += ["", "## Demographic changes", "", "| Incident | Field | Old → new | Evidence |", "|---|---|---|---|"]
    lines.extend(f"| {row['incident_id']} | {field} | {before} → {after} | {cell(row['evidence_quotes'])} |" for row, field, before, after in demographic_rows)
    lines += ["", "## Invariant check", "", f"Violations: {len(invariant_rows)}."]
    lines.extend(f"- {incident_id}: {kind}" for incident_id, kind in invariant_rows)
    lines += ["", "## Main counts filled by explicit listed people", ""]
    lines.extend(f"- {row['incident_id']}: {cell(row['proposed'])} — {cell(row['evidence_quotes'])}" for row in sum_listed_rows)
    non_lebanese_rows = [row for row in rows if "non_lebanese_casualties_excluded" in row.get("audit_payload", "")]
    lines += ["", "## Non-Lebanese casualties excluded", ""]
    lines.extend(f"- {row['incident_id']}: {cell(row['note_extra'])}" for row in non_lebanese_rows)
    human_rule_breaks = []
    for row in rows:
        if row.get("classification") != "skipped_admin_edited" or not row.get("proposed"):
            continue
        values = json.loads(row["proposed"])
        broken = []
        for base, total, details in (("deaths", "total_deaths", ("detail.male_d", "detail.female_d", "detail.children_d")), ("injuries", "total_injuries", ("detail.male_i", "detail.female_i", "detail.children_i"))):
            listed = sum(values.get(field) or 0 for field in details)
            if (values.get(total) is None) != (values.get(base) is None) or (values.get(total) is None and listed) or (values.get(total) is not None and values[total] < listed):
                broken.append(base)
        if broken:
            human_rule_breaks.append((row, broken))
    lines += ["", "## Human edits that break the field rules", "", "These rows are excluded from the automatic invariant gate and are not changed.", "", "| Incident | Broken sides | Values | Editor/time audit |", "|---|---|---|---|"]
    lines.extend(f"| {row['incident_id']} | {', '.join(broken)} | {cell(row['proposed'])} | {cell(row['admin_edit_info'])} |" for row, broken in human_rule_breaks)
    lost_second_claim = 0
    subset_as_main = 0
    cross_claim_demographics = 0
    for row in rows:
        if not row.get("proposed") or not row.get("chosen_claims"):
            continue
        proposed = json.loads(row["proposed"])
        selected = json.loads(row["chosen_claims"])
        inspected_texts: set[str] = set()
        for side in ("deaths", "injuries"):
            choice = selected.get(side)
            if not choice:
                continue
            claim_text = choice.get("claim_text") or ""
            units = _claim_units(claim_text)
            unit_id = str(choice.get("claim_id") or "").split(":", 1)[-1]
            matching = [values for candidate_id, _text, values, _listed in units if candidate_id == unit_id]
            if not matching or matching[0].get(side) != proposed.get(side):
                subset_as_main += 1
            if claim_text and claim_text not in inspected_texts:
                inspected_texts.add(claim_text)
                unit_sides = {
                    candidate_side
                    for _candidate_id, _text, values, _listed in units
                    for candidate_side in ("deaths", "injuries")
                    if values.get(candidate_side) is not None
                }
                if unit_sides == {"deaths", "injuries"} and any(proposed.get(candidate_side) is None for candidate_side in unit_sides):
                    lost_second_claim += 1
        # Claim-level resolution writes a side's main and demographics in one
        # operation. Any differing provenance recorded here is a regression.
        for side, fields in (("deaths", ("detail.male_d", "detail.female_d", "detail.children_d")), ("injuries", ("detail.male_i", "detail.female_i", "detail.children_i"))):
            if any(proposed.get(field) is not None for field in fields) and side not in selected:
                cross_claim_demographics += 1
    lines += ["", "## Claim-integrity corpus checks", "", f"- subset-as-main: {subset_as_main}", f"- cross-claim demographics: {cross_claim_demographics}", f"- lost second claim: {lost_second_claim}"]
    chosen_rows = [row for row in rows if row.get("classification") in ("corrected", "conflict_flagged")]
    lines += ["", "## Chosen claims for changed/conflicting rows", "", "| Incident | Chosen claims and competing claims |", "|---|---|"]
    lines.extend(f"| {row['incident_id']} | {cell(row['chosen_claims'])} |" for row in chosen_rows)
    previous_rows = _previous_rows()
    previous_counts = Counter(row.get("classification", "") for row in previous_rows.values())
    lines += ["", "## Count diff versus Round 5", "", "| Class | Round 5 | Final | Diff |", "|---|---:|---:|---:|"]
    for name in (*CLASSES, "failed"):
        current = failed if name == "failed" else counts[name]
        prior = previous_counts.get(name, 0)
        lines.append(f"| {name} | {prior} | {current} | {current - prior:+d} |")
    lines += ["", "## Apply semantics", "", "| Class | Incident casualty result | Verification | Reviewable destination | Audit reason_code |", "|---|---|---|---|---|"]
    semantics = {
        "corrected": ("replace with validated local claims; every lowering requires disproof_code/text", "unchanged unless an existing conflict applies", "source evidence and incident update audit payload", "repair"),
        "unchanged": ("no change", "no change", "existing incident/source evidence", "none"),
        "needs_reextraction": ("no change", "no automatic flag change", "report/re-extraction queue candidate", "none"),
        "source_missing": ("no change", "no automatic flag change", "report for source recovery", "none"),
        "village_mismatch": ("remove values from the wrong village", "needs_verification with owning village(s) and removed numbers", "owner/removal audit payload", "repair"),
        "bulletin_aggregate": ("remove shared values from village row", "no village-conflict flag", "live raw: bulletin group; snapshot-only: repair audit payload", "repair"),
        "conflict_flagged": ("retain deterministic owner-source value", "needs_verification with conflict detail", "all conflicting source claims and incident update", "repair"),
        "approximate_flagged": ("do not store phrase as an exact count", "needs_verification (vague count)", "phrase in audit payload and report", "repair"),
        "needs_business_decision": ("no change", "no automatic flag change", "business-decision section and source excerpts", "none"),
        "skipped_admin_edited": ("no change", "preserve human decision", "existing human edit audit", "none"),
        "failed": ("rolled back", "no change", "failure row", "none"),
    }
    for name in (*CLASSES, "failed"):
        lines.append(f"| {name} | {' | '.join(semantics[name])} |")
    changed_since_round3 = []
    for row in rows:
        previous = previous_rows.get(row["incident_id"])
        if previous is None or any(previous.get(key, "") != str(row.get(key, "")) for key in ("classification", "proposed")):
            changed_since_round3.append((previous, row))
    lines += ["", "## Changed since Round 4", "", "| Incident | Class before → after | Values before → after | Source excerpt |", "|---|---|---|---|"]
    for previous, row in changed_since_round3:
        lines.append(
            f"| {cell(row['incident_id'])} | {cell((previous or {}).get('classification', 'not in Round 4'))} → {cell(row['classification'])} | "
            f"{cell((previous or {}).get('proposed', 'not in Round 4'))} → {cell(row['proposed'])} | {cell(row['source_excerpt'][:300])} |"
        )
    lines += ["", "## Incidents", "", "| Incident | Village | Date | Current | Proposed | Class | Reason | Attributed villages | Sources | Evidence | Aggregate evidence | Aggregate storage |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for row in rows:
        lines.append("| " + " | ".join(cell(row[key]) for key in ("incident_id", "village", "date", "current", "proposed", "classification", "reason", "attributed_villages", "source_ids", "evidence_quotes", "aggregate_quotes", "aggregate_storage")) + " |")
    unchanged = [row for row in rows if row["classification"] == "unchanged"]
    with_values = [row for row in unchanged if any(value is not None for value in json.loads(row["proposed"]).values())]
    possible_misses = [row for row in unchanged if not any(value is not None for value in json.loads(row["proposed"]).values()) and str(row["source_has_casualty_word"]).lower() == "true"]
    rng = random.Random(20261014)
    value_sample = rng.sample(with_values, min(20, len(with_values)))
    miss_sample = rng.sample(possible_misses, min(10, len(possible_misses)))
    lines += ["", "## Fixed-seed sample of unchanged incidents with casualty values", "", f"Requested 20; available without duplication: {len(value_sample)}.", "", "| Incident | Village | Proposed | Sources | Evidence |", "|---|---|---|---|---|"]
    lines.extend(f"| {cell(row['incident_id'])} | {cell(row['village'])} | {cell(row['proposed'])} | {cell(row['source_ids'])} | {cell(row['evidence_quotes'])} |" for row in value_sample)
    lines += ["", "## Fixed-seed sample of unchanged empty incidents with casualty wording", "", f"Requested 10; available without duplication: {len(miss_sample)}.", "", "| Incident | Village | Sources | Evidence | Aggregate/source excerpt |", "|---|---|---|---|---|"]
    lines.extend(f"| {cell(row['incident_id'])} | {cell(row['village'])} | {cell(row['source_ids'])} | {cell(row['evidence_quotes'])} | {cell(row['aggregate_quotes'] or row['aggregate_source_text'] or row['source_excerpt'])} |" for row in miss_sample)
    common_names = sorted({alias for alias, _, _ in aliases if _requires_location_context([item[0] for item in re.finditer(r"[\u0600-\u06ff]+", alias)])})
    lines += ["", "## Common-word gazetteer names requiring location context", "", ", ".join(common_names) or "None."]
    business_rows = [row for row in rows if row["classification"] == "needs_business_decision"]
    lines += ["", "## Needs business decision: non-Lebanese casualties", "", "These rows are intentionally unchanged pending a policy decision.", "", "| Incident | Village | Current | Source excerpt |", "|---|---|---|---|"]
    lines.extend(f"| {cell(row['incident_id'])} | {cell(row['village'])} | {cell(row['current'])} | {cell(row['source_excerpt'][:300])} |" for row in business_rows)
    increases = []
    for row in rows:
        if row["classification"] not in ("corrected", "conflict_flagged"): continue
        old, new = json.loads(row["current"]), json.loads(row["proposed"])
        if any(isinstance(new.get(key), int) and new[key] > (old.get(key) if isinstance(old.get(key), int) else -1) for key in new): increases.append(row)
    lines += ["", "## Corrected rows with increases", "", "| Incident | Current | Proposed | Evidence |", "|---|---|---|---|"]
    lines.extend(f"| {cell(row['incident_id'])} | {cell(row['current'])} | {cell(row['proposed'])} | {cell(row['evidence_quotes'])} |" for row in increases)
    disproved_rows = [row for row in rows if row["classification"] == "corrected" and _lowered_fields(json.loads(row["current"]), json.loads(row["proposed"]))]
    lines += ["", "## Lowered corrected rows: positive disproof", "", "| Incident | Village | Disproof code | Disproving text | Source excerpt |", "|---|---|---|---|---|"]
    lines.extend(f"| {cell(row['incident_id'])} | {cell(row['village'])} | {cell(row['disproof_code'])} | {cell(row['disproving_text'])} | {cell(row['source_excerpt'][:300])} |" for row in disproved_rows)
    disproof_counts = Counter(row["disproof_code"] for row in disproved_rows)
    lines += ["", "### Disproof-code counts", ""] + ([f"- {code}: {count}" for code, count in sorted(disproof_counts.items())] or ["- none: 0"])
    round4_disproved_ids = {
        incident_id for incident_id, previous in previous_rows.items()
        if previous.get("reason") == "stored values positively disproved by deterministic count/evidence validation"
    }
    round4_disproved = [row for row in rows if row["incident_id"] in round4_disproved_ids]
    lines += ["", "## Round 4 unproved-disproof audit", "", f"Rows reviewed: {len(round4_disproved)}.", "", "| Incident | Village | Round 5 class | Disproof code | Disproving text | Source excerpt |", "|---|---|---|---|---|---|"]
    lines.extend(f"| {cell(row['incident_id'])} | {cell(row['village'])} | {cell(row['classification'])} | {cell(row['disproof_code'] or 'none — not disproved')} | {cell(row['disproving_text'])} | {cell(row['source_excerpt'][:300])} |" for row in round4_disproved)
    reviewed_code_counts = Counter(row["disproof_code"] or "none — not disproved" for row in round4_disproved)
    lines += ["", "### Round 4 unproved-disproof code counts", ""] + [f"- {code}: {count}" for code, count in sorted(reviewed_code_counts.items())]
    snapshot_aggregates = [row for row in rows if "merged_from_snapshot" in row.get("aggregate_storage", "")]
    lines += ["", "## Snapshot-only bulletin aggregates", "", f"Count: {len(snapshot_aggregates)}. Stored for review in the automatic repair audit payload because the bulletin-group schema requires a live raw-message foreign key.", "", "| Incident | Storage |", "|---|---|"]
    lines.extend(f"| {cell(row['incident_id'])} | {cell(row['aggregate_storage'])} |" for row in snapshot_aggregates)
    mismatch_example = next((row for row in rows if row["classification"] == "village_mismatch"), None)
    lines += ["", "## Village-mismatch audit payload example", "", "```json", mismatch_example["audit_payload"] if mismatch_example else "{}", "```"]
    reasons: dict[str, int] = {}
    for row in rows:
        if row["classification"] == "corrected": reasons[row["reason"]] = reasons.get(row["reason"], 0) + 1
    lines += ["", "## Corrected reason breakdown", ""] + [f"- {reason}: {count}" for reason, count in sorted(reasons.items())]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"processed={len(rows)} succeeded={len(rows)-failed} failed={failed}")
    print(md_path)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
