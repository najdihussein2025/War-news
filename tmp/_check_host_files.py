from pathlib import Path

print("HOST:")
for rel in [
    "app/news/services/dedup_matching_service.py",
    "app/news/repositories/emergency_organization_repository.py",
    "app/news/services/incident_materialization_service.py",
]:
    p = Path(rel)
    t = p.read_text(encoding="utf-8")
    print(
        rel,
        "DCS=",
        "DuplicateComparisonService" in t,
        "old_window=",
        "settings.dedup_time_window_days" in t,
        "column_valued=",
        "column_valued" in t,
        "sole=",
        "sole verdict" in t,
        "size=",
        p.stat().st_size,
    )
