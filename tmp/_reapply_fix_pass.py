"""Atomically re-apply Phase-1 fix-pass files to current package paths."""
from __future__ import annotations

import os
import runpy
import shutil
import stat
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _write(rel: str, src: str) -> None:
    path = ROOT / rel
    source = ROOT / src
    if path.exists():
        try:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        except OSError:
            pass
    path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    print("wrote", rel, path.stat().st_size)


def main() -> None:
    os.chdir(ROOT)
    _write("app/news/services/dedup/dedup_matching_service.py", "tmp/_canonical_dedup_matching_service.py")
    _write("app/news/repositories/emergency_organization_repository.py", "tmp/_patch_emergency_organization_repository.py")
    _write("app/core/seeds/seed_emergency_organizations.py", "tmp/_patch_seed_emergency_organizations.py")
    _write("app/news/interfaces/dedup_matching_interface.py", "tmp/_patch_dedup_matching_interface.py")
    _write("tests/test_dedup_matching_service.py", "tmp/_canonical_test_dedup_matching_service.py")
    _write("tests/test_emergency_organization_repository.py", "tmp/_patch_test_emergency_organization_repository.py")

    runpy.run_path(str(ROOT / "tmp/_apply_materialization_patch.py"), run_name="__main__")
    runpy.run_path(str(ROOT / "tmp/_apply_mat_test_patch.py"), run_name="__main__")

    # keep materialization test import on new package path
    mat_test = ROOT / "tests/test_incident_materialization_service.py"
    tt = mat_test.read_text(encoding="utf-8")
    tt2 = tt.replace(
        "from app.news.services.incident_materialization_service import",
        "from app.news.services.materialization.incident_materialization_service import",
    )
    if tt2 != tt:
        mat_test.write_text(tt2, encoding="utf-8")
        print("fixed mat test import")

    cfg = ROOT / "app/core/config.py"
    t = cfg.read_text(encoding="utf-8")
    if "DEPRECATED for verdict decisions" not in t:
        old = """    # Incident-level dedup look-back window (full materialization / embedding-weighted
    # DedupMatchingService only). The fast-path incident-level signal no longer uses
    # this flat window — it is threshold-driven via DuplicateComparisonService (below)
    # with dedup_fastpath_lookup_window_days as the outer query bound instead.
    dedup_time_window_days: int = 3"""
        new = """    # DEPRECATED for verdict decisions. Soft/embedding DedupMatchingService and
    # fast-path both gate accept/reject via DuplicateComparisonService (6h tiers)
    # with dedup_fastpath_lookup_window_days as the outer candidate query bound.
    # Kept only for any remaining callers that still read the flat window.
    dedup_time_window_days: int = 3"""
        if old not in t:
            raise SystemExit("config block missing")
        cfg.write_text(t.replace(old, new, 1), encoding="utf-8")
        print("config updated")
    else:
        print("config ok")

    checks = {
        "app/news/services/dedup/dedup_matching_service.py": "DuplicateComparisonService",
        "app/news/repositories/emergency_organization_repository.py": "column_valued",
        "app/news/services/materialization/incident_materialization_service.py": "sole verdict",
        "app/core/seeds/seed_emergency_organizations.py": "accounts.models",
        "tests/test_incident_materialization_service.py": "merges_without_re_score",
        "tests/test_dedup_matching_service.py": "mansouri_style_gap",
    }
    for rel, needle in checks.items():
        text = (ROOT / rel).read_text(encoding="utf-8")
        if needle not in text:
            raise SystemExit(f"MISSING {needle!r} in {rel}")
        print("ok", rel)

    shutil.copy2(
        ROOT / "app/news/services/materialization/incident_materialization_service.py",
        ROOT / "tmp/_patched_incident_materialization_service.py",
    )


if __name__ == "__main__":
    main()
