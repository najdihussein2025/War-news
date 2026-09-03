from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings
from app.core.ollama_client import OllamaChatClient
from app.llm.dtos import ExtractionResult
from app.llm.services.ollama_extraction_service import OllamaExtractionService
from app.news.services.casualty_transition_backstop import (
    casualty_transition_keyword_labels,
    detect_casualty_transition_backstop,
)

REPORT_PATH = PROJECT_ROOT / "Docs" / "recon" / "casualty-transition-live-validation.md"

SEARCH_MODE_PATTERNS: dict[str, tuple[str, ...]] = {
    "transition": (
        "%توفي%",
        "%متوف%",
        "%فارق الحياة%",
        "%من الجرحى%",
        "%أحد الجرحى%",
        "%بقي%",
    ),
    "casualty": (
        "%جريح%",
        "%جرحى%",
        "%إصابة%",
        "%اصابة%",
        "%شهداء%",
        "%قتيل%",
    ),
    "additive": (
        "%إضاف%",
        "%اضاف%",
        "%جدد%",
        "%ارتفع%",
        "%حصيلة%",
        "%أصيب%",
    ),
    "followup_death": (
        "%أحد جريحي%",
        "%أحد الجرحى%",
        "%متأثر%بجراح%",
        "%متأثرا%بجراح%",
        "%متأثرة%بجراح%",
        "%استشهاد%جريح%",
    ),
}

COMPOUND_SEARCHES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "transition_casualty": (
        SEARCH_MODE_PATTERNS["transition"],
        SEARCH_MODE_PATTERNS["casualty"],
    ),
    "additive_casualty": (
        SEARCH_MODE_PATTERNS["additive"],
        SEARCH_MODE_PATTERNS["casualty"],
    ),
}


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    category: str
    origin: str
    raw_text: str
    expected_transitions: list[dict[str, Any]]
    notes: str
    raw_message_id: int | None = None
    source_name: str | None = None
    received_at: str | None = None


def _candidate_query(mode: str) -> str:
    if mode in COMPOUND_SEARCHES:
        left_patterns, right_patterns = COMPOUND_SEARCHES[mode]
        left_clauses = "\n            or ".join(
            f"raw_text ilike :p{index}" for index, _ in enumerate(left_patterns, start=1)
        )
        offset = len(left_patterns)
        right_clauses = "\n            or ".join(
            f"raw_text ilike :p{offset + index}"
            for index, _ in enumerate(right_patterns, start=1)
        )
        where_clause = f"({left_clauses})\n          and (\n            {right_clauses}\n          )"
    else:
        patterns = SEARCH_MODE_PATTERNS[mode]
        where_clause = "\n            or ".join(
            f"raw_text ilike :p{index}" for index, _ in enumerate(patterns, start=1)
        )
    return textwrap.dedent(
        f"""
        select
          id,
          source_name,
          received_at,
          raw_text
        from raw_messages
        where raw_text is not null
          and (
            {where_clause}
          )
        order by received_at desc
        limit :limit
        """
    ).strip()


def _resolve_database_url() -> str:
    raw = os.environ.get("DATABASE_URL", settings.database_url)
    url = make_url(raw)
    if url.host == "db":
        return str(url.set(host="localhost"))
    return raw


def _build_db_engine() -> Engine:
    return create_engine(_resolve_database_url())


def _build_extraction_service() -> OllamaExtractionService:
    client = OllamaChatClient(
        base_url=os.environ.get("OLLAMA_BASE_URL", settings.ollama_base_url),
        api_key=os.environ.get("OLLAMA_API_KEY", settings.ollama_api_key),
        model=os.environ.get(
            "EXTRACTION_OLLAMA_MODEL",
            settings.extraction_ollama_model,
        ),
        timeout_seconds=settings.ollama_timeout_seconds,
    )
    return OllamaExtractionService(client)


def list_candidates(limit: int, mode: str) -> int:
    if mode in COMPOUND_SEARCHES:
        patterns = COMPOUND_SEARCHES[mode][0] + COMPOUND_SEARCHES[mode][1]
    else:
        patterns = SEARCH_MODE_PATTERNS[mode]
    engine = _build_db_engine()
    with engine.connect() as conn:
        params: dict[str, Any] = {"limit": limit}
        for index, pattern in enumerate(patterns, start=1):
            params[f"p{index}"] = pattern
        rows = conn.execute(
            text(_candidate_query(mode)),
            params,
        ).mappings()
        for row in rows:
            _safe_print(f"id={row['id']}")
            _safe_print(f"source={row['source_name']}")
            _safe_print(f"received_at={row['received_at']}")
            _safe_print(row["raw_text"])
            _safe_print("---")
    return 0


def _normalize_transitions(result: ExtractionResult) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in result.casualty_transitions]


def _transition_match(
    expected: list[dict[str, Any]],
    actual: list[dict[str, Any]],
) -> bool:
    return expected == actual


def _report_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _safe_print(value: str) -> None:
    text_value = value if value.endswith("\n") else f"{value}\n"
    sys.stdout.buffer.write(text_value.encode("utf-8", errors="replace"))


def _load_eval_cases(path: Path) -> list[EvalCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases: list[EvalCase] = []
    for item in payload:
        cases.append(
            EvalCase(
                case_id=item["case_id"],
                category=item["category"],
                origin=item["origin"],
                raw_text=item["raw_text"],
                expected_transitions=item["expected_transitions"],
                notes=item["notes"],
                raw_message_id=item.get("raw_message_id"),
                source_name=item.get("source_name"),
                received_at=item.get("received_at"),
            )
        )
    return cases


def _category_summary(results: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for result in results:
        category = result["category"]
        bucket = summary.setdefault(category, {"pass": 0, "fail": 0, "blocked": 0})
        if result.get("error"):
            bucket["blocked"] += 1
        else:
            bucket["pass" if result["passed"] else "fail"] += 1
    return summary


def _build_verdict(summary: dict[str, dict[str, int]]) -> str:
    if any(bucket.get("blocked", 0) > 0 for bucket in summary.values()):
        return (
            "Validation was blocked by extractor runtime errors, so prompt "
            "effectiveness could not be re-scored from this environment."
        )
    restated = summary.get("transition_plus_restated", {"pass": 0, "fail": 0})
    death_only = summary.get("transition_only_death_followup", {"pass": 0, "fail": 0})
    additive = summary.get("additive_no_transition", {"pass": 0, "fail": 0})
    if restated["fail"] > 0:
        return (
            "Needs targeted prompt revision. The model missed at least one "
            "explicit injury-to-death follow-up with a restated casualty tally."
        )
    if death_only["fail"] > 0:
        return (
            "Needs targeted prompt revision. The priority failure mode "
            "was missed on death-only follow-up text."
        )
    if additive["fail"] > 0:
        return (
            "Needs targeted prompt revision. The model over-triggered on at "
            "least one additive-only update."
        )
    return "Reliable as-is for this spot-check."


def _build_backstop_summary(results: list[dict[str, Any]]) -> dict[str, int]:
    expected_transition_cases = [
        item for item in results if item["expected_transitions"]
    ]
    llm_misses = [item for item in expected_transition_cases if not item["passed"]]
    caught = [
        item for item in llm_misses if item["keyword_backstop_hit"]
    ]
    false_positives = [
        item
        for item in results
        if not item["expected_transitions"] and item["keyword_backstop_hit"]
    ]
    return {
        "expected_transition_cases": len(expected_transition_cases),
        "llm_misses_after_prompt": len(llm_misses),
        "backstop_caught_llm_misses": len(caught),
        "backstop_false_positives": len(false_positives),
    }


def _build_revision_backstop_section(
    results: list[dict[str, Any]],
) -> str:
    summary = _category_summary(results)
    totals = _build_backstop_summary(results)
    named_cases = {
        item["case_id"]: item
        for item in results
    }

    lines: list[str] = []
    lines.append("## Revision + Backstop Results")
    lines.append("")
    lines.append("### Updated Prompt Text")
    lines.append("")
    lines.append(
        "Applied to both the standalone Tier-1 extractor and the combined Tier-1 prompt:"
    )
    lines.append("")
    lines.append("- Mandatory rule: explicit previously-injured-to-deceased wording must emit `[{'from_status':'injured','to_status':'deceased','count':1}]` even when a new total or remaining-injured tally is also stated.")
    lines.append("- Explicitly named forms: `استشهاد أحد جريحي/الجرحى`, `وفاة أحد المصابين متأثراً بجراحه`, `فارق أحد الجرحى الحياة`.")
    lines.append("- Multi-clause rule: the transition trigger and refreshed tally can appear in different clauses of the same long sentence and still describe one follow-up update.")
    lines.append("")
    lines.append("### Keyword Backstop")
    lines.append("")
    for label in casualty_transition_keyword_labels():
        lines.append(f"- `{label}`")
    lines.append("")
    lines.append("### Step 3 Re-Validation")
    lines.append("")
    for result in results:
        status = (
            "BLOCKED"
            if result.get("error")
            else ("PASS" if result["passed"] else "FAIL")
        )
        lines.append(
            f"- `{result['case_id']}`: "
            f"`{status}`; "
            f"llm_transition=`{bool(result['actual_transitions'])}`; "
            f"backstop_hit=`{result['keyword_backstop_hit']}`"
        )
    lines.append("")
    lines.append(
        f"- Houla (`supp_transition_death_only_houla`): "
        f"`{'BLOCKED' if named_cases['supp_transition_death_only_houla'].get('error') else ('PASS' if named_cases['supp_transition_death_only_houla']['passed'] else 'FAIL')}`"
    )
    lines.append(
        f"- Mifdoun (`real_transition_restate_mifdoun_425`): "
        f"`{'BLOCKED' if named_cases['real_transition_restate_mifdoun_425'].get('error') else ('PASS' if named_cases['real_transition_restate_mifdoun_425']['passed'] else 'FAIL')}`"
    )
    lines.append("")
    lines.append("### Backstop Catch Rate")
    lines.append("")
    lines.append(
        f"- Expected transition cases: `{totals['expected_transition_cases']}`"
    )
    lines.append(
        f"- LLM misses after prompt revision: `{totals['llm_misses_after_prompt']}`"
    )
    lines.append(
        f"- Backstop caught LLM misses: `{totals['backstop_caught_llm_misses']}`"
    )
    lines.append(
        f"- False positives on additive-no-transition cases: `{totals['backstop_false_positives']}`"
    )
    lines.append("")
    lines.append(
        "Judgment: keep the current reconciliation narrow for now. "
        "The implemented review flag is only for `LLM=[]` plus a positive keyword signal. "
        "The inverse case (`LLM transition` with no keyword support) looks lower-priority and more likely to add review noise on real phrasing variants, so it is better tracked as a future hardening option."
    )
    if any(item.get("error") for item in results):
        lines.append("")
        lines.append(
            "Live extractor note: this run was blocked before model evaluation by a connection error to the local Ollama endpoint, so the Step 3 LLM pass/fail statuses remain unavailable from this sandboxed environment."
        )
    lines.append("")
    lines.append("### Category Breakdown")
    lines.append("")
    for category, bucket in summary.items():
        lines.append(
            f"- `{category}`: `{bucket['pass']} passed / {bucket['fail']} failed / {bucket['blocked']} blocked`"
        )
    lines.append("")
    return "\n".join(lines)


def _write_report(
    cases: list[EvalCase],
    results: list[dict[str, Any]],
    *,
    report_path: Path,
) -> None:
    summary = _category_summary(results)
    total_pass = sum(1 for item in results if item["passed"])
    total_blocked = sum(1 for item in results if item.get("error"))
    total_fail = len(results) - total_pass - total_blocked

    lines: list[str] = []
    lines.append("# Casualty Transition Live Validation")
    lines.append("")
    lines.append(f"- Model: `{results[0]['model'] if results else settings.extraction_ollama_model}`")
    lines.append(f"- Cases: `{len(cases)}`")
    lines.append(
        f"- Overall: `{total_pass} passed / {total_fail} failed / {total_blocked} blocked`"
    )
    lines.append(f"- Verdict: {_build_verdict(summary)}")
    lines.append("")
    lines.append("## Evaluation Set")
    lines.append("")
    for case in cases:
        lines.append(f"### {case.case_id}")
        lines.append(f"- Category: `{case.category}`")
        lines.append(f"- Origin: `{case.origin}`")
        if case.raw_message_id is not None:
            lines.append(f"- Raw message id: `{case.raw_message_id}`")
        if case.source_name:
            lines.append(f"- Source: `{case.source_name}`")
        if case.received_at:
            lines.append(f"- Received at: `{case.received_at}`")
        lines.append(f"- Notes: {case.notes}")
        lines.append("- Raw text:")
        lines.append("")
        lines.append("```text")
        lines.append(case.raw_text)
        lines.append("```")
        lines.append("")
    lines.append("## Per-Message Results")
    lines.append("")
    for result in results:
        lines.append(f"### {result['case_id']}")
        lines.append(f"- Category: `{result['category']}`")
        status = (
            "BLOCKED"
            if result.get("error")
            else ("PASS" if result["passed"] else "FAIL")
        )
        lines.append(f"- Result: `{status}`")
        lines.append(f"- Elapsed seconds: `{result['elapsed_seconds']:.2f}`")
        if result.get("error"):
            lines.append(f"- Error: `{result['error']}`")
        lines.append("- Expected:")
        lines.append("")
        lines.append("```json")
        lines.append(_report_json(result["expected_transitions"]))
        lines.append("```")
        lines.append("")
        lines.append("- Actual:")
        lines.append("")
        lines.append("```json")
        lines.append(_report_json(result["actual_transitions"]))
        lines.append("```")
        lines.append("")
        lines.append("- Full extraction:")
        lines.append("")
        lines.append("```json")
        lines.append(_report_json(result["full_result"]))
        lines.append("```")
        lines.append("")
    lines.append("## Category Breakdown")
    lines.append("")
    for category, bucket in summary.items():
        lines.append(
            f"- `{category}`: `{bucket['pass']} passed / {bucket['fail']} failed / {bucket['blocked']} blocked`"
        )
    lines.append("")
    lines.append("## Final Verdict")
    lines.append("")
    lines.append(_build_verdict(summary))
    lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")


def run_validation(eval_cases_path: Path, report_path: Path) -> int:
    cases = _load_eval_cases(eval_cases_path)
    service = _build_extraction_service()
    results: list[dict[str, Any]] = []

    for index, case in enumerate(cases, start=1):
        _safe_print(f"Running {index}/{len(cases)}: {case.case_id}")
        started_at = time.perf_counter()
        try:
            result = service.extract_tier1(
                case.raw_text,
                raw_message_id=case.raw_message_id or index,
            )
            actual_transitions = _normalize_transitions(result)
            full_result: dict[str, Any] | None = result.model_dump(mode="json")
            model = result.model
            error: str | None = None
        except Exception as exc:
            actual_transitions = []
            full_result = None
            model = service.client.model
            error = f"{type(exc).__name__}: {exc}"
        results.append(
            {
                "case_id": case.case_id,
                "category": case.category,
                "origin": case.origin,
                "expected_transitions": case.expected_transitions,
                "actual_transitions": actual_transitions,
                "passed": _transition_match(
                    case.expected_transitions,
                    actual_transitions,
                ) and error is None,
                "elapsed_seconds": time.perf_counter() - started_at,
                "model": model,
                "full_result": full_result,
                "error": error,
                "keyword_backstop_hit": detect_casualty_transition_backstop(
                    case.raw_text
                ).plausible,
            }
        )

    _write_report(cases, results, report_path=report_path)
    _safe_print("")
    _safe_print(_build_revision_backstop_section(results))
    _safe_print(f"Wrote {report_path}")
    for item in results:
        status = (
            "BLOCKED"
            if item.get("error")
            else ("PASS" if item["passed"] else "FAIL")
        )
        _safe_print(
            f"{status} {item['case_id']} "
            f"expected={_report_json(item['expected_transitions'])} "
            f"actual={_report_json(item['actual_transitions'])}"
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list-candidates", action="store_true")
    parser.add_argument("--candidate-limit", type=int, default=40)
    parser.add_argument(
        "--search-mode",
        choices=sorted({*SEARCH_MODE_PATTERNS.keys(), *COMPOUND_SEARCHES.keys()}),
        default="transition",
    )
    parser.add_argument(
        "--eval-cases",
        type=Path,
        default=PROJECT_ROOT / "scripts" / "phase2-extraction-live-check" / "casualty_transition_eval_cases.json",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=REPORT_PATH,
    )
    parser.add_argument(
        "--case-id",
        action="append",
        help="Run only a named evaluation case. May be passed more than once.",
    )
    args = parser.parse_args()

    if args.list_candidates:
        return list_candidates(args.candidate_limit, args.search_mode)
    eval_cases_path = args.eval_cases.resolve()
    if args.case_id:
        all_cases = json.loads(eval_cases_path.read_text(encoding="utf-8"))
        selected = [case for case in all_cases if case["case_id"] in args.case_id]
        if len(selected) != len(args.case_id):
            parser.error("One or more --case-id values did not match the evaluation set.")
        selected_path = eval_cases_path.with_name("selected_casualty_transition_eval_cases.json")
        selected_path.write_text(json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8")
        eval_cases_path = selected_path
    return run_validation(eval_cases_path, args.report_path.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
