#!/usr/bin/env python
"""Fail if Alembic / app / tests / scripts still import pre-reorg service paths.

The services reorg moved modules under concern subpackages (pipeline/, dedup/,
matching/, incidents/, …). A one-off grep during that work covered only
``app/``, ``tests/``, and ``scripts/`` — so ``alembic/`` still had a stale
import that blocked ``alembic upgrade head`` for every later revision.

Run from repo root:

  python scripts/check_stale_service_imports.py

Exit 0 when clean; exit 1 and print matches when stale imports remain.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = ("app", "tests", "scripts", "alembic")

# Flat module names that were relocated into concern subpackages.
# Keep in sync with the reorg layout; intentionally listed explicitly so new
# legitimate top-level modules under services/ do not false-positive.
STALE_FLAT_MODULES = (
    "pipeline_orchestrator",
    "pipeline_concurrent_sweeps",
    "pipeline_sweep_stages",
    "pipeline_llm_workers",
    "pipeline_health_service",
    "pipeline_jobs",
    "pipeline_stage_run_service",
    "pipeline_advisory_lock",
    "pre_extraction_dedup",
    "fast_path_dedup",
    "fast_path_eligibility",
    "duplicate_comparison_service",
    "dedup_matching_service",
    "duplicate_match_reconciliation",
    "incident_merge_service",
    "matching_service",
    "village_matching_service",
    "condition_resolution_service",
    "condition_aliases",
    "condition_evidence_override",
    "emergency_organization_matching_service",
    "tier2_detail_fill_service",
    "category_mapper",
    "casualty_demographic_consistency",
    "casualty_gender_evidence",
    "casualty_transition_merge",
    "casualty_transition_backstop",
    "incident_detail_field_registry",
    "incident_detail_merge",
    "incident_detail_edit_service",
    "incident_detail_rollups",
    "incident_detail_category_serializer",
    "incident_materialization_service",
    "clustering_service",
    "embedding_service",
    "raw_message_embedding_service",
    "air_violation_service",
    "air_violation_workbook_service",
    "air_violation_khabar_import",
    "red_alert_air_violation_service",
    "incident_service",
    "incident_workbook_service",
    "imported_incident_enrichment",
    "incident_event_stream",
)

_MODULE_ALT = "|".join(re.escape(m) for m in STALE_FLAT_MODULES)
STALE_IMPORT_RE = re.compile(
    rf"(?:from|import)\s+app\.news\.services\.(?:{_MODULE_ALT})\b"
)


def iter_python_files() -> list[Path]:
    files: list[Path] = []
    for root_name in SCAN_ROOTS:
        root = ROOT / root_name
        if not root.is_dir():
            continue
        files.extend(root.rglob("*.py"))
    return sorted(files)


def main() -> int:
    hits: list[str] = []
    for path in iter_python_files():
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"WARN could not read {path}: {exc}", file=sys.stderr)
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            if STALE_IMPORT_RE.search(line):
                rel = path.relative_to(ROOT).as_posix()
                hits.append(f"{rel}:{line_no}: {line.strip()}")

    if hits:
        print("Stale pre-reorg service imports found:")
        for hit in hits:
            print(f"  {hit}")
        print(
            "\nUpdate imports to the concern subpackage "
            "(pipeline/, dedup/, matching/, incidents/, …)."
        )
        return 1

    print(
        "OK: no stale flat app.news.services.* imports in "
        + ", ".join(SCAN_ROOTS)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
