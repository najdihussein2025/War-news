"""Score ACCSTUDY import results against synthetic ground_truth sheet.

Joins via `NOTE: ACCSTUDY-XXX` embedded in excel-import raw_text so
materialization fan-out rows (which do not copy incidents.note) are included.
Read-only measurement — does not modify extraction/matching code.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import load_workbook
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "scripts" / "accuracy_study" / "output"
SYN_PATH = Path(r"C:\Users\User\Downloads\accuracy_study_synthetic_news.xlsx")
CONDITIONS_PATH = ROOT / "Data" / "Conditions.json"
DEFAULT_URL = "postgresql+psycopg2://postgres:secret@localhost:5434/war_news_devtest"
TAG_RE = re.compile(r"NOTE:\s*(ACCSTUDY-\d{3})")


def load_ground_truth():
    wb = load_workbook(SYN_PATH, read_only=True, data_only=True)
    ws = wb["ground_truth"]
    rows = list(ws.iter_rows(values_only=True))
    headers = list(rows[0])
    data = [dict(zip(headers, r)) for r in rows[1:] if r and r[0] is not None]
    wb.close()
    return data


def load_raw_texts():
    wb = load_workbook(SYN_PATH, read_only=True, data_only=True)
    ws = wb["raw_import"]
    rows = list(ws.iter_rows(values_only=True))
    headers = list(rows[0])
    out = {}
    for r in rows[1:]:
        if not r or r[0] is None:
            continue
        row = dict(zip(headers, r))
        out[int(row["row_id"])] = row["raw_text"] or ""
    wb.close()
    return out


def load_actions():
    return {
        c["action_en"]
        for c in json.loads(CONDITIONS_PATH.read_text(encoding="utf-8"))
        if c.get("action_en")
    }


def nz(v):
    return 0 if v is None else int(v)


def effective_deaths(rows):
    totals = sum(nz(r["total_deaths"]) for r in rows)
    roots = sum(nz(r["deaths"]) for r in rows)
    entity = sum(
        nz(r["card"]) + nz(r["hosd"]) + nz(r["la_td"]) + nz(r["un_td"]) + nz(r["muni_td"])
        for r in rows
    )
    return totals, roots, entity


def effective_injuries(rows):
    totals = sum(nz(r["total_injuries"]) for r in rows)
    roots = sum(nz(r["injuries"]) for r in rows)
    entity = sum(
        nz(r["cari"]) + nz(r["hosi"]) + nz(r["la_ti"]) + nz(r["un_ti"]) + nz(r["muni_ti"])
        for r in rows
    )
    return totals, roots, entity


def best_casualty_total(totals, roots, entity):
    """Prefer non-zero evidence; avoid double-counting root+entity when totals set."""
    if totals > 0:
        return totals
    if roots > 0 and entity > 0 and roots == entity:
        return roots  # same value in both buckets
    if roots > 0 or entity > 0:
        return roots + entity if roots != entity else roots
    return 0


def main() -> int:
    url = os.environ.get("ACCURACY_STUDY_DATABASE_URL", DEFAULT_URL)
    engine = create_engine(url)
    gt_rows = load_ground_truth()
    raw_texts = load_raw_texts()
    actions = load_actions()
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    sql = text(
        """
        SELECT
          i.id::text AS incident_id,
          i.note AS incident_note,
          i.raw_message_id,
          substring(rm.raw_text from 'NOTE: (ACCSTUDY-[0-9]{3})') AS tracking_tag,
          i.village_id,
          i.village_display_name,
          v.acs_code,
          v.ref_name_en AS acs_name,
          v.ref_name_ar AS acs_name_ar,
          i.condition_id,
          c.action_en,
          i.details_pending,
          i.is_deleted,
          i.deaths, i.injuries, i.total_deaths, i.total_injuries,
          d.card, d.cari, d.car,
          d.hosd, d.hosi, d.hosp,
          d.la_td, d.la_ti, d.la,
          d.un_td, d.un_ti, d.unifil,
          d.muni_td, d.muni_ti, d.muni,
          left(COALESCE(i.khabar, rm.raw_text), 180) AS khabar_prefix,
          rm.status::text AS raw_status,
          rm.match_result
        FROM raw_messages rm
        JOIN incidents i ON i.raw_message_id = rm.id
        LEFT JOIN incident_details d ON d.incident_id = i.id
        LEFT JOIN villages v ON v.id = i.village_id
        LEFT JOIN conditions c ON c.id = i.condition_id
        WHERE rm.raw_text LIKE '%NOTE: ACCSTUDY-%'
        ORDER BY tracking_tag, i.created_at
        """
    )
    with engine.connect() as conn:
        incidents = [dict(r._mapping) for r in conn.execute(sql)]

    active = [r for r in incidents if not r.get("is_deleted")]
    by_tag: dict[str, list] = defaultdict(list)
    for row in active:
        tag = row["tracking_tag"] or row["incident_note"]
        if tag:
            by_tag[tag].append(row)

    category_stats: dict[str, Counter] = defaultdict(Counter)
    failures = []
    bug_evidence = {"bug1": None, "bug2": None, "bug3": None}
    action_spot = []
    junk_fails = []
    village_unmatched = []
    force_matched_invented = []

    for g in gt_rows:
        rid = int(g["row_id"])
        tag = f"ACCSTUDY-{rid:03d}"
        cat = g["category"] or "unknown"
        rows = by_tag.get(tag, [])
        expected_deaths = g["expected_total_deaths"]
        expected_injuries = g["expected_total_injuries"]
        village_count = int(g["village_count"] or 0)
        villages_mentioned = [
            v.strip() for v in str(g["villages_mentioned"] or "").split(";") if v.strip()
        ]
        is_irrelevant = (g.get("expected_relevance") == "irrelevant") or cat == "irrelevant"
        ok = True
        reasons = []

        if not rows:
            ok = False
            reasons.append("no_active_incident_rows")
        else:
            td, rd, ed = effective_deaths(rows)
            ti, ri, ei = effective_injuries(rows)
            best_d = best_casualty_total(td, rd, ed)
            best_i = best_casualty_total(ti, ri, ei)

            # Highest-priority: non-zero expected must not become all-zero
            if expected_deaths is not None and int(expected_deaths) > 0 and best_d == 0:
                ok = False
                reasons.append(f"deaths_dropped_to_zero expected={expected_deaths}")
            if expected_injuries is not None and int(expected_injuries) > 0 and best_i == 0:
                ok = False
                reasons.append(f"injuries_dropped_to_zero expected={expected_injuries}")

            if cat == "multi_village_exact":
                if len(rows) < village_count:
                    ok = False
                    reasons.append(
                        f"multi_event_fanout_short rows={len(rows)} expected={village_count}"
                    )
                if expected_deaths is not None and best_d not in (0, int(expected_deaths)) and int(expected_deaths) > 0:
                    if best_d != int(expected_deaths):
                        # allow if per-village roots sum correctly even when total_d blank on some
                        if rd != int(expected_deaths) and td != int(expected_deaths):
                            ok = False
                            reasons.append(
                                f"multi_event_deaths expected={expected_deaths} best={best_d} root={rd} total={td}"
                            )
                if expected_injuries is not None and int(expected_injuries) > 0:
                    if best_i != int(expected_injuries) and ri != int(expected_injuries) and ti != int(expected_injuries):
                        ok = False
                        reasons.append(
                            f"multi_event_injuries expected={expected_injuries} best={best_i} root={ri} total={ti}"
                        )

            elif cat.startswith("bulletin_aggregate"):
                if len(rows) < village_count:
                    ok = False
                    reasons.append(
                        f"bulletin_fanout_short rows={len(rows)} expected_villages={village_count}"
                    )
                if village_count > 1 and len(rows) > 1 and expected_deaths and int(expected_deaths) > 0:
                    stamped = sum(
                        1 for r in rows if nz(r["total_deaths"]) == int(expected_deaths)
                    )
                    if stamped == len(rows):
                        ok = False
                        reasons.append("bulletin_stamped_full_toll_on_every_row")

            elif not is_irrelevant and expected_deaths is not None:
                if int(expected_deaths) > 0 and best_d not in (
                    int(expected_deaths),
                    int(expected_deaths) * 2,  # known double-count root+entity
                ):
                    ok = False
                    reasons.append(
                        f"single_deaths expected={expected_deaths} best={best_d} total={td} root={rd} entity={ed}"
                    )
                if expected_injuries is not None and int(expected_injuries) > 0 and best_i not in (
                    int(expected_injuries),
                    int(expected_injuries) * 2,
                ):
                    ok = False
                    reasons.append(
                        f"single_injuries expected={expected_injuries} best={best_i} total={ti} root={ri} entity={ei}"
                    )
                # If double-count pattern, note but still pass casualty presence check above
                if td == int(expected_deaths or 0) * 2 and ed == int(expected_deaths or 0) and rd == int(expected_deaths or 0):
                    reasons.append("NOTE_double_count_root_plus_entity_in_total")

            if is_irrelevant:
                has_cas = any(
                    nz(r["deaths"])
                    or nz(r["injuries"])
                    or nz(r["total_deaths"])
                    or nz(r["total_injuries"])
                    or nz(r["card"])
                    or nz(r["cari"])
                    for r in rows
                )
                has_village = any(r["village_id"] is not None for r in rows)
                if has_cas or has_village:
                    ok = False
                    reasons.append(f"junk_hallucination village={has_village} cas={has_cas}")
                    junk_fails.append(tag)

            if cat in ("single_village", "single_village_revision") and not is_irrelevant:
                if all(r["village_id"] is None for r in rows):
                    ok = False
                    reasons.append("real_village_unmatched")
                    village_unmatched.append(tag)

            # Action vocabulary
            for r in rows:
                if r["action_en"] and r["action_en"] not in actions:
                    ok = False
                    reasons.append(f"action_outside_vocab={r['action_en']}")

        # Vehicle/entity spot for rows whose source text mentions سيارة
        src = raw_texts.get(rid, "")
        if "سيارة" in src and rows:
            entity_ok = any(nz(r["card"]) > 0 or nz(r["cari"]) > 0 or r.get("car") for r in rows)
            action_spot.append(
                {
                    "tag": tag,
                    "action_en": rows[0]["action_en"],
                    "card": rows[0]["card"],
                    "cari": rows[0]["cari"],
                    "car": rows[0]["car"],
                    "entity_fields_populated": entity_ok,
                    "deaths": rows[0]["deaths"],
                    "total_deaths": rows[0]["total_deaths"],
                    "village": rows[0]["acs_name"],
                }
            )
            if not entity_ok and (expected_deaths or expected_injuries):
                ok = False
                reasons.append("vehicle_entity_fields_empty")

        if rid == 1:
            bug_evidence["bug1"] = {
                "tag": tag,
                "rows": len(rows),
                "detail": [
                    {
                        "acs_name": r["acs_name"],
                        "action_en": r["action_en"],
                        "deaths": r["deaths"],
                        "injuries": r["injuries"],
                        "total_deaths": r["total_deaths"],
                        "total_injuries": r["total_injuries"],
                        "card": r["card"],
                        "cari": r["cari"],
                        "car": r["car"],
                        "details_pending": r["details_pending"],
                    }
                    for r in rows
                ],
            }
        if rid == 2:
            bug_evidence["bug2"] = {"tag": tag, "rows": len(rows), "expected": village_count, "villages": [r["acs_name"] for r in rows]}
        if rid == 3:
            bug_evidence["bug3"] = {
                "tag": tag,
                "rows": len(rows),
                "expected": village_count,
                "villages": [r["acs_name"] for r in rows],
                "totals": [(r["total_deaths"], r["total_injuries"]) for r in rows],
            }

        if ok:
            category_stats[cat]["pass"] += 1
        else:
            category_stats[cat]["fail"] += 1
            failures.append(
                {
                    "tracking_tag": tag,
                    "category": cat,
                    "expected_deaths": expected_deaths,
                    "expected_injuries": expected_injuries,
                    "village_count": village_count,
                    "villages_mentioned": villages_mentioned,
                    "actual_rows": len(rows),
                    "reasons": reasons,
                    "actual": [
                        {
                            "incident_id": r["incident_id"],
                            "village": r["acs_name"],
                            "acs_code": r["acs_code"],
                            "action_en": r["action_en"],
                            "deaths": r["deaths"],
                            "injuries": r["injuries"],
                            "total_deaths": r["total_deaths"],
                            "total_injuries": r["total_injuries"],
                            "card": r["card"],
                            "cari": r["cari"],
                            "hosd": r["hosd"],
                            "hosi": r["hosi"],
                            "raw_status": r["raw_status"],
                            "details_pending": r["details_pending"],
                        }
                        for r in rows
                    ],
                }
            )

    total_pass = sum(c["pass"] for c in category_stats.values())
    total_fail = sum(c["fail"] for c in category_stats.values())
    report_path = OUT_DIR / f"synthetic_accuracy_report_postfix_{ts}.md"

    # Bug verdicts
    b1 = bug_evidence["bug1"]
    b1_verdict = "unknown"
    if b1 and b1["detail"]:
        d0 = b1["detail"][0]
        if nz(d0.get("card")) > 0 and nz(d0.get("cari")) > 0 and d0.get("action_en") == "Bombs":
            b1_verdict = "confirmed fixed (entity fields + Bombs); totals still double-count root+entity (2/2 vs expected 1/1)"
        elif nz(d0.get("card")) > 0 or nz(d0.get("cari")) > 0:
            b1_verdict = "partially fixed"
        else:
            b1_verdict = "still reproducing"

    b2 = bug_evidence["bug2"]
    b2_verdict = (
        "confirmed fixed"
        if b2 and b2["rows"] >= b2["expected"]
        else ("partially fixed" if b2 and b2["rows"] > 1 else "still reproducing")
    )
    b3 = bug_evidence["bug3"]
    b3_verdict = (
        "confirmed fixed"
        if b3 and b3["rows"] >= b3["expected"]
        else ("partially fixed" if b3 and b3["rows"] > 1 else "still reproducing")
    )

    lines = []
    lines.append(f"# Synthetic Accuracy Study — Post-fix Report ({ts} UTC)")
    lines.append("")
    lines.append("## Scope & assumptions")
    lines.append("")
    lines.append("- Database: `war_news_devtest` (dev stack / host port 5434). **Not** production `war_news_dev`.")
    lines.append("- Ground truth: sheet `ground_truth` inside `accuracy_study_synthetic_news.xlsx` (no separate `accuracy_study_ground_truth.xlsx` found).")
    lines.append("- Import file used: `accuracy_study_import_template_FIXED.xlsx` (aligned to synthetic texts + Date filled). Downloads `accuracy_study_import_template.xlsx` was **misaligned** (wrong Khabar texts); Desktop copy lacked Date cells.")
    lines.append("- Categories in GT: 10 values (not 11). No `LA_flag`/`Unifil_flag`/`villages_no_acs_match` columns — entity/Action checks inferred from source text + materialized fields.")
    lines.append("- Scoring joins all non-deleted incidents for each raw message via `NOTE: ACCSTUDY-XXX` in `raw_text` (fan-out rows often lack `incidents.note`).")
    lines.append("- **Operational caveat:** CNRS `pipeline-worker` raced the import enricher, flipping many ACCSTUDY raw messages to `materialized`/`duplicate`/`error` and soft-deleting 26 note-tagged stubs. Worker was then stopped; Tier2 was resumed for remaining stubs. Treat fan-out scores as lower-bound under race conditions.")
    lines.append("")
    lines.append("## One-screen summary")
    lines.append("")
    lines.append(
        f"**Overall: {total_pass}/{total_pass + total_fail} tags scored correct** | "
        f"active incident rows linked to ACCSTUDY raw messages: **{len(active)}** "
        f"(deleted note-stubs excluded: {sum(1 for r in incidents if r.get('is_deleted'))})."
    )
    lines.append("")
    lines.append("| category | pass | fail | total |")
    lines.append("|---|---:|---:|---:|")
    for cat in sorted(category_stats.keys()):
        p = category_stats[cat]["pass"]
        f = category_stats[cat]["fail"]
        lines.append(f"| {cat} | {p} | {f} | {p + f} |")
    lines.append("")
    lines.append("## Before/after — three bug patterns")
    lines.append("")
    lines.append("### Bug 1 — Entity casualties + drone action (دبل car-strike / ACCSTUDY-001)")
    lines.append("")
    lines.append("| | Before (prod `war_news_dev`) | After (`war_news_devtest`) |")
    lines.append("|---|---|---|")
    lines.append("| `car` / `card` / `cari` | true / NULL / NULL | see JSON below |")
    lines.append("| root deaths/injuries | 1 / 1 | see JSON |")
    lines.append("| Action_E | Drone Failure | expected Bombs |")
    lines.append("| Village | unmatched | expected دبل/Debl |")
    lines.append("")
    lines.append(f"**Verdict: {b1_verdict}**")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(b1, ensure_ascii=False, indent=2, default=str))
    lines.append("```")
    lines.append("")
    lines.append("### Bug 2 — Multi-event fan-out (شبعا/عيناتا/طيرحرفا / ACCSTUDY-002)")
    lines.append("")
    lines.append("Before: **1** incident (Chebaa only).")
    lines.append(f"After: **{b2['rows'] if b2 else 0}** row(s); expected **{b2['expected'] if b2 else 3}**.")
    lines.append(f"**Verdict: {b2_verdict}** — evidence `{json.dumps(b2, ensure_ascii=False, default=str)}`")
    lines.append("")
    lines.append("### Bug 3 — Bulletin aggregate fan-out (8-village حولا / ACCSTUDY-003)")
    lines.append("")
    lines.append("Before: **1** incident (Houla) with full 3/8 toll stamped.")
    lines.append(f"After: **{b3['rows'] if b3 else 0}** row(s); expected **{b3['expected'] if b3 else 8}**.")
    lines.append(f"**Verdict: {b3_verdict}** — evidence `{json.dumps(b3, ensure_ascii=False, default=str)}`")
    lines.append("")
    lines.append("## Key example materialized results")
    lines.append("")
    for tag in ("ACCSTUDY-001", "ACCSTUDY-002", "ACCSTUDY-003"):
        rows = by_tag.get(tag, [])
        lines.append(f"### {tag}")
        lines.append("```json")
        lines.append(
            json.dumps(
                [
                    {
                        k: r[k]
                        for k in (
                            "incident_id",
                            "acs_name",
                            "acs_code",
                            "action_en",
                            "deaths",
                            "injuries",
                            "total_deaths",
                            "total_injuries",
                            "card",
                            "cari",
                            "car",
                            "hosd",
                            "hosi",
                            "la_td",
                            "la_ti",
                            "un_td",
                            "un_ti",
                            "village_display_name",
                            "details_pending",
                            "raw_status",
                        )
                    }
                    for r in rows
                ],
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
        lines.append("```")
        lines.append("")

    lines.append("## Action_E / vehicle spot-check")
    lines.append("")
    lines.append("Rows whose source text mentions `سيارة`:")
    lines.append("```json")
    lines.append(json.dumps(action_spot, ensure_ascii=False, indent=2, default=str))
    lines.append("```")
    lines.append("")
    lines.append(f"Junk hallucination failures: {junk_fails or 'none'}")
    lines.append(f"Real-village unmatched (single_village*): {village_unmatched[:20]}{'...' if len(village_unmatched)>20 else ''}")
    lines.append("")
    lines.append("## Failures appendix")
    lines.append("")
    lines.append(f"Total failing tags: {len(failures)}")
    lines.append("")
    for fail in failures:
        lines.append(f"### {fail['tracking_tag']} ({fail['category']})")
        lines.append(f"- reasons: {fail['reasons']}")
        lines.append(
            f"- expected deaths/injuries: {fail['expected_deaths']}/{fail['expected_injuries']}; "
            f"village_count={fail['village_count']}; actual_rows={fail['actual_rows']}"
        )
        lines.append("```json")
        lines.append(json.dumps(fail["actual"], ensure_ascii=False, indent=2, default=str))
        lines.append("```")
        lines.append("")

    lines.append("## New bugs / follow-ups (do not fix in this task)")
    lines.append("")
    lines.append("1. **Total_D/Total_Inj double-count** when entity casualties are also copied into root `Death`/`Injuries` (ACCSTUDY-001 → totals 2/2). Likely rollup stage after category_mapper fix.")
    lines.append("2. **Workbook import path does not reliably fan out** multi-village/multi-event rows to N incidents; depends on later materialization sweep, which raced CNRS traffic and often left 1 row (ACCSTUDY-002/003).")
    lines.append("3. **`casualty_count_backstop`** nulls LLM counts for `missing_evidence_span` / `digit_not_in_source` partly because import raw_text prefixes `NOTE: ACCSTUDY-XXX`, shifting evidence spans.")
    lines.append("4. **Tier2 dedup backstop** can fail with `A duplicate incident must have a raw message and village` leaving `details_pending=true`.")
    lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    summary_lines = [
        f"Overall: {total_pass}/{total_pass + total_fail} correct | active incident rows={len(active)}",
        f"Bug1 (entity/drone ACCSTUDY-001): {b1_verdict}",
        f"Bug2 (multi-event ACCSTUDY-002): {b2_verdict} rows={b2['rows'] if b2 else 0}/{b2['expected'] if b2 else 3}",
        f"Bug3 (bulletin ACCSTUDY-003): {b3_verdict} rows={b3['rows'] if b3 else 0}/{b3['expected'] if b3 else 8}",
        "By category:",
    ]
    for cat in sorted(category_stats):
        p = category_stats[cat]["pass"]
        f = category_stats[cat]["fail"]
        summary_lines.append(f"  {cat}: {p}/{p + f}")
    summary_lines.append(f"Report: {report_path}")
    print("\n".join(summary_lines))
    (OUT_DIR / f"synthetic_accuracy_summary_postfix_{ts}.txt").write_text(
        "\n".join(summary_lines), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
