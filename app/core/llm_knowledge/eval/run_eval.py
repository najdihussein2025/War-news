"""Standalone eval harness for llm_knowledge corpus files.

PowerShell usage (from repo root):

    python -m app.core.llm_knowledge.eval.run_eval
    python -m app.core.llm_knowledge.eval.run_eval --live
    python -m app.core.llm_knowledge.eval.run_eval --live --report Docs/recon/llm_knowledge_live_validation.md

Default mode does not call Ollama. ``--live`` triggers real model calls
(~150s each on CPU) against a representative subset of the corpus.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.llm_knowledge.loader import PromptBuilder
from app.core.llm_knowledge.prompt_assembly import build_stage_system_prompt

CORPUS_DIR = Path(__file__).resolve().parent / "corpus"
REPO_ROOT = Path(__file__).resolve().parents[4]

STAGE_BY_CORPUS: dict[str, str] = {
    "relevance_filter.jsonl": "relevance_filter",
    "tier1_extraction.jsonl": "tier1_extraction",
    "casualty_scope.jsonl": "casualty_scope",
    "village_matching.jsonl": "village_matching",
    "revision_detection.jsonl": "story_revision",
}

# Live subset: one case per corpus file floor + every B.1 real_bug entry.
# Identified by bug_ref (stable) rather than line index.
LIVE_BUG_REFS: tuple[str, ...] = (
    # tier1 / gender / transitions
    "vague-quantifier-null",
    "gendered-occupation-paramedic-in-mixed-toll",
    "casualty-transition-followup",
    "transition-with-restated-remaining-injuries",
    "additive-injuries-not-transition",
    "occupation-gender-male-paramedic",
    "occupation-gender-female-paramedic",
    # casualty scope / merge
    "multi-village-casualty-misattribution",
    "multi-village-null-not-zero-or-shared",
    "merge-blind-max-wins",
    # village (one positive alias + one ambiguous collision)
    "maslakh-neighborhood",
    "bare-fouqa-collision",
    # revision
    "preliminary-toll-revision",
    "named-victim-zahraa-revision",
    "rising-toll-revision",
    "preliminary-tally-marker",
)

# Corpus labels whose rules live in another built stage. casualty_scope rules
# are part of the Tier 1 prompt; village matching is code-only in production
# (no LLM stage), so offline checks only need a loadable prompt.
BUILD_STAGE_BY_LABEL: dict[str, str] = {
    "casualty_scope": "tier1_extraction",
    "village_matching": "tier1_extraction",
}

# Production default is the separate presence + general Tier 1 calls
# (tier1_use_combined_presence_extraction=False). Pass
# --extraction-prompt combined_tier1 to score the combined variant instead.
DEFAULT_EXTRACTION_PROMPT_STAGE = "tier1_extraction"
EXTRACTION_SHAPED_LABELS = ("tier1_extraction", "casualty_scope")
LIVE_SKIPPED_LABELS = frozenset({"village_matching"})


def _live_stage_override(extraction_prompt_stage: str) -> dict[str, str]:
    return {label: extraction_prompt_stage for label in EXTRACTION_SHAPED_LABELS}


LIVE_STAGE_OVERRIDE: dict[str, str] = _live_stage_override(
    DEFAULT_EXTRACTION_PROMPT_STAGE
)


def _log(message: str = "") -> None:
    print(message, flush=True)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
            if isinstance(payload, dict):
                cases.append(payload)
    return cases


def _check_case(
    case: dict[str, Any],
    *,
    stage: str,
    builder: PromptBuilder,
    root: Path,
) -> tuple[bool, str]:
    input_text = str(case.get("input") or "")
    expected = case.get("expected_output") or {}
    context = builder.build(BUILD_STAGE_BY_LABEL.get(stage, stage), input_text)

    if not context.rules.strip() and stage != "relevance_filter":
        return False, "no rules loaded"

    if stage == "tier1_extraction" and ("؛" in input_text or " - " in input_text):
        if "rules/tier1_multi_village.md" not in context.situational_rules_loaded:
            if "مرج" in input_text or "؛" in input_text:
                return False, "expected tier1_multi_village situational rule"

    if stage == "casualty_scope":
        scope = expected.get("casualty_scope")
        if scope == "per_village_exact" and ":" in input_text:
            return True, "per-village clause pattern present"
        if scope == "bulletin_aggregate":
            return True, "aggregate pattern accepted (LLM eval pending)"
        if scope == "unspecified":
            return True, "no-casualty case accepted"
        if expected.get("casualty_transitions") or expected.get("merge_rule"):
            return True, "transition/merge rule case documented"

    if stage == "village_matching":
        acs = expected.get("resolved_parent_acs")
        if acs is not None:
            return True, f"alias case documented (ACS {acs}); matcher eval pending Phase 3"
        if expected.get("match") is None:
            return True, "ambiguous/unresolved case documented"

    if stage == "story_revision":
        hint = expected.get("relationship_hint")
        if hint == "revision":
            marker = expected.get("matched_keyword_contains") or ""
            if marker and marker not in context.as_prompt_fragment() and marker not in input_text:
                terms_blob = " ".join(
                    getattr(t, "term", str(t)) for t in (context.terminology or [])
                )
                if marker and marker not in terms_blob and marker not in input_text:
                    return False, f"revision marker not in knowledge: {marker}"
            return True, "revision case documented"
        return True, "non-revision case documented"

    if not context.as_prompt_fragment().strip():
        return False, "empty prompt fragment"

    return True, "ok"


def run_eval() -> int:
    builder = PromptBuilder()
    root = builder.root
    total_pass = 0
    total_fail = 0

    corpus_files = sorted(CORPUS_DIR.glob("*.jsonl"))
    if not corpus_files:
        print("No corpus files found.")
        return 1

    for corpus_path in corpus_files:
        stage = STAGE_BY_CORPUS.get(corpus_path.name, "tier1_extraction")
        cases = _load_jsonl(corpus_path)
        file_pass = 0
        file_fail = 0
        print(f"\n=== {corpus_path.name} ({len(cases)} cases, stage={stage}) ===")
        for index, case in enumerate(cases, start=1):
            ok, reason = _check_case(case, stage=stage, builder=builder, root=root)
            if ok:
                file_pass += 1
                print(f"  PASS [{index}] {reason}")
            else:
                file_fail += 1
                print(f"  FAIL [{index}] {reason}")
                print(f"         input: {case.get('input', '')[:120]}")
                print(
                    f"         expected: {json.dumps(case.get('expected_output'), ensure_ascii=False)}"
                )
        total_pass += file_pass
        total_fail += file_fail
        print(f"  -> {file_pass} passed, {file_fail} failed")

    print(f"\nTotal: {total_pass} passed, {total_fail} failed")
    return 0 if total_fail == 0 else 1


def _select_live_cases() -> list[tuple[str, str, dict[str, Any]]]:
    """Return (corpus_file, stage, case) rows for the live subset."""
    wanted = set(LIVE_BUG_REFS)
    selected: list[tuple[str, str, dict[str, Any]]] = []
    seen_refs: set[str] = set()

    for corpus_path in sorted(CORPUS_DIR.glob("*.jsonl")):
        stage = STAGE_BY_CORPUS.get(corpus_path.name, "tier1_extraction")
        for case in _load_jsonl(corpus_path):
            bug_ref = str(case.get("bug_ref") or "")
            if bug_ref in wanted and bug_ref not in seen_refs:
                selected.append((corpus_path.name, stage, case))
                seen_refs.add(bug_ref)

    missing = wanted - seen_refs
    if missing:
        _log(f"WARNING: live subset missing bug_refs: {sorted(missing)}")
    return selected


def _live_user_prompt(stage: str, case: dict[str, Any]) -> str:
    text = str(case.get("input") or "")
    if stage == "story_revision":
        return (
            "Classify whether this Arabic bulletin is a toll/story revision "
            "follow-up. Return JSON only with keys: "
            "relationship_hint (\"revision\" or null), matched_keywords (array of strings).\n\n"
            f"Text:\n{text}"
        )
    if stage == "village_matching":
        return (
            "Resolve this Lebanese place string. Return JSON only with keys: "
            "resolved_name_ar (string or null), resolved_parent_acs (int or null), "
            "reason (string; use ambiguous_or_unresolved when unsure).\n\n"
            f"Place:\n{text}"
        )
    return text


def _score_live(
    stage: str,
    expected: dict[str, Any],
    actual: Any,
) -> tuple[str, str]:
    """Return (pass|partial|fail, note). Never mutates expected."""
    if not isinstance(actual, dict):
        return "fail", f"non-object model output: {type(actual).__name__}"

    if stage in {"tier1_extraction", "casualty_scope"}:
        checks: list[tuple[str, bool]] = []
        exp_cas = expected.get("casualties")
        act_cas = actual.get("casualties") if isinstance(actual.get("casualties"), dict) else {}
        if isinstance(exp_cas, dict):
            for key, value in exp_cas.items():
                if key.endswith("_at_least"):
                    field = key.replace("_at_least", "")
                    got = act_cas.get(field)
                    ok = isinstance(got, int) and got >= int(value)
                    checks.append((f"casualties.{field}>={value}", ok))
                elif value is None:
                    checks.append((f"casualties.{key}=null", act_cas.get(key) is None))
                else:
                    checks.append((f"casualties.{key}={value}", act_cas.get(key) == value))

        if "casualty_scope" in expected:
            checks.append(
                (
                    f"casualty_scope={expected['casualty_scope']}",
                    actual.get("casualty_scope") == expected["casualty_scope"],
                )
            )

        if "casualty_transitions" in expected:
            exp_t = expected["casualty_transitions"]
            act_t = actual.get("casualty_transitions") or []
            if exp_t == []:
                checks.append(("casualty_transitions=[]", act_t == [] or act_t is None))
            elif isinstance(exp_t, list) and exp_t:
                ok = isinstance(act_t, list) and len(act_t) >= 1
                if ok and isinstance(act_t[0], dict):
                    ok = (
                        act_t[0].get("from_status") == exp_t[0].get("from_status")
                        and act_t[0].get("to_status") == exp_t[0].get("to_status")
                    )
                checks.append(("casualty_transitions", ok))

        if "village" in expected:
            checks.append(("village present", bool(actual.get("village"))))

        if "sub_events_count" in expected:
            subs = actual.get("sub_events") or []
            checks.append(
                (
                    f"sub_events_count={expected['sub_events_count']}",
                    isinstance(subs, list) and len(subs) == expected["sub_events_count"],
                )
            )

        if not checks:
            return "partial", "no comparable fields; raw output retained"
        passed = sum(1 for _, ok in checks if ok)
        detail = ", ".join(f"{name}:{'Y' if ok else 'N'}" for name, ok in checks)
        if passed == len(checks):
            return "pass", detail
        if passed:
            return "partial", detail
        return "fail", detail

    if stage == "story_revision":
        exp_hint = expected.get("relationship_hint")
        act_hint = actual.get("relationship_hint")
        if exp_hint == "revision":
            if act_hint == "revision":
                marker = expected.get("matched_keyword_contains")
                keywords = actual.get("matched_keywords") or []
                if marker and isinstance(keywords, list) and any(marker in str(k) for k in keywords):
                    return "pass", "revision + marker"
                if marker:
                    return "partial", f"revision but marker missing ({marker})"
                return "pass", "revision"
            return "fail", f"expected revision, got {act_hint!r}"
        if act_hint in (None, "null", ""):
            return "pass", "non-revision"
        return "partial", f"expected null hint, got {act_hint!r}"

    if stage == "village_matching":
        if expected.get("match") is None and expected.get("reason") == "ambiguous_or_unresolved":
            reason = str(actual.get("reason") or "")
            acs = actual.get("resolved_parent_acs")
            if acs is None or "ambiguous" in reason or "unresolved" in reason:
                return "pass", "left unresolved/ambiguous"
            return "fail", f"expected unresolved, got acs={acs}"
        exp_acs = expected.get("resolved_parent_acs")
        if exp_acs is not None:
            if actual.get("resolved_parent_acs") == exp_acs:
                return "pass", f"ACS {exp_acs}"
            if actual.get("resolved_parent_acs") is None:
                return "partial", f"expected ACS {exp_acs}, model abstained"
            return "fail", f"expected ACS {exp_acs}, got {actual.get('resolved_parent_acs')}"

    return "partial", "unscored stage shape"


def run_live(
    *,
    report_path: Path | None,
    extraction_prompt_stage: str = DEFAULT_EXTRACTION_PROMPT_STAGE,
) -> int:
    from app.core.config import settings
    from app.core.ollama_client import OllamaChatClient, OllamaChatMessage

    selected = _select_live_cases()
    if not selected:
        _log("No live cases selected.")
        return 1

    _log("=== LIVE OLLAMA VALIDATION ===")
    _log(f"Host: {settings.ollama_base_url}")
    _log(f"Model: {settings.extraction_ollama_model}")
    _log(f"Cases: {len(selected)} (~{len(selected) * 150}s ceiling)")
    _log("bug_refs: " + ", ".join(str(c.get("bug_ref")) for _, _, c in selected))
    _log("This step makes real Ollama calls. Do not run silently in larger batches.")

    client = OllamaChatClient(
        base_url=settings.ollama_base_url,
        api_key=settings.ollama_api_key,
        model=settings.extraction_ollama_model,
        timeout_seconds=max(settings.extraction_llm_timeout_seconds, 180),
        max_request_retries=settings.extraction_llm_request_retries,
        retry_backoff_seconds=settings.extraction_llm_retry_backoff_seconds,
    )

    results: list[dict[str, Any]] = []
    for index, (corpus_name, stage, case) in enumerate(selected, start=1):
        if stage in LIVE_SKIPPED_LABELS:
            _log(
                f"\n[{index}/{len(selected)}] {corpus_name} :: "
                "skipped (no LLM stage in production)"
            )
            continue
        bug_ref = case.get("bug_ref")
        prompt_stage = _live_stage_override(extraction_prompt_stage).get(stage, stage)
        input_text = str(case.get("input") or "")
        expected = case.get("expected_output") or {}
        _log(f"\n[{index}/{len(selected)}] {corpus_name} :: {bug_ref} (prompt_stage={prompt_stage})")
        started = time.perf_counter()
        try:
            system = build_stage_system_prompt(prompt_stage, input_text)
            user = _live_user_prompt(stage, case)
            raw = client.chat(
                [
                    OllamaChatMessage(role="system", content=system),
                    OllamaChatMessage(role="user", content=user),
                ],
                response_format="json",
                temperature=0.0,
            )
            elapsed = time.perf_counter() - started
            try:
                actual = json.loads(raw.strip())
            except json.JSONDecodeError:
                actual = {"_raw": raw}
            verdict, note = _score_live(stage, expected, actual)
            _log(f"  {verdict.upper()} ({elapsed:.1f}s) — {note}")
            results.append(
                {
                    "corpus": corpus_name,
                    "stage": stage,
                    "prompt_stage": prompt_stage,
                    "bug_ref": bug_ref,
                    "source": case.get("source"),
                    "input": input_text,
                    "expected_output": expected,
                    "actual_output": actual,
                    "verdict": verdict,
                    "note": note,
                    "elapsed_seconds": round(elapsed, 1),
                }
            )
        except Exception as exc:  # noqa: BLE001 — report per-case failures
            elapsed = time.perf_counter() - started
            _log(f"  FAIL ({elapsed:.1f}s) — exception: {exc}")
            results.append(
                {
                    "corpus": corpus_name,
                    "stage": stage,
                    "prompt_stage": prompt_stage,
                    "bug_ref": bug_ref,
                    "source": case.get("source"),
                    "input": input_text,
                    "expected_output": expected,
                    "actual_output": None,
                    "verdict": "fail",
                    "note": f"exception: {exc}",
                    "elapsed_seconds": round(elapsed, 1),
                }
            )

    counts = {
        "pass": sum(1 for r in results if r["verdict"] == "pass"),
        "partial": sum(1 for r in results if r["verdict"] == "partial"),
        "fail": sum(1 for r in results if r["verdict"] == "fail"),
    }
    _log(
        f"\nLive summary: {counts['pass']} pass / {counts['partial']} partial / {counts['fail']} fail"
    )

    out = report_path or (REPO_ROOT / "Docs" / "recon" / "llm_knowledge_live_validation.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    _write_live_report(out, results, counts, client.model)
    _log(f"Wrote report: {out}")
    return 0 if counts["fail"] == 0 else 1


def _write_live_report(
    path: Path,
    results: list[dict[str, Any]],
    counts: dict[str, int],
    model: str,
) -> None:
    lines = [
        "# llm_knowledge live validation run",
        "",
        f"**Date (UTC):** {datetime.now(timezone.utc).isoformat()}",
        f"**Model:** `{model}`",
        f"**Summary:** {counts['pass']} pass / {counts['partial']} partial / {counts['fail']} fail",
        "",
        "Policy: `expected_output` was **not** edited to match the model. "
        "Mismatches are left for manual review.",
        "",
        "| # | bug_ref | corpus | verdict | note | seconds |",
        "|---|---------|--------|---------|------|--------:|",
    ]
    for index, row in enumerate(results, start=1):
        lines.append(
            f"| {index} | `{row.get('bug_ref')}` | `{row.get('corpus')}` | "
            f"**{row.get('verdict')}** | {row.get('note')} | {row.get('elapsed_seconds')} |"
        )

    lines.extend(["", "## Per-case detail", ""])
    for index, row in enumerate(results, start=1):
        lines.append(f"### {index}. `{row.get('bug_ref')}` — {row.get('verdict')}")
        lines.append("")
        lines.append(f"- corpus: `{row.get('corpus')}` / stage `{row.get('stage')}` "
                     f"(prompt `{row.get('prompt_stage')}`)")
        lines.append(f"- note: {row.get('note')}")
        lines.append("")
        lines.append("Input:")
        lines.append("")
        lines.append("```")
        lines.append(str(row.get("input") or ""))
        lines.append("```")
        lines.append("")
        lines.append("Expected:")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(row.get("expected_output"), ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")
        if row.get("verdict") != "pass":
            lines.append("Actual (failure/partial):")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(row.get("actual_output"), ensure_ascii=False, indent=2))
            lines.append("```")
            lines.append("")
            # Belief note placeholder for reviewer — filled by scoring note above.
            if row.get("verdict") == "fail":
                lines.append(
                    "**Reviewer note:** treat as prompt/knowledge gap unless expected_output "
                    "is demonstrably wrong; do not auto-edit the corpus."
                )
                lines.append("")
        else:
            lines.append("_Actual omitted (pass)._")
            lines.append("")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="llm_knowledge eval harness")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run real Ollama calls on a representative corpus subset (~150s/call).",
    )
    parser.add_argument(
        "--report",
        type=str,
        default="",
        help="Markdown report path for --live (default Docs/recon/llm_knowledge_live_validation.md).",
    )
    parser.add_argument(
        "--extraction-prompt",
        choices=("tier1_extraction", "combined_tier1"),
        default=DEFAULT_EXTRACTION_PROMPT_STAGE,
        help="Tier 1 prompt to score for --live (production default: tier1_extraction).",
    )
    args = parser.parse_args(argv)
    if args.live:
        report = Path(args.report) if args.report else None
        return run_live(
            report_path=report,
            extraction_prompt_stage=args.extraction_prompt,
        )
    return run_eval()


if __name__ == "__main__":
    sys.exit(main())
