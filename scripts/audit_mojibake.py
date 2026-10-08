"""Read-only inventory of UTF-8 Arabic text that was mojibake-decoded."""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

ROOTS = ("app", "scripts", "tests", "Data", "alembic")
SUFFIXES = {".py", ".yaml", ".yml", ".md", ".json", ".sql"}
MARKERS = ("Ø", "Ù", "Ã")


def repaired(value: str) -> str | None:
    if not any(marker in value for marker in MARKERS):
        return None
    candidate = value
    for _ in range(3):
        next_value = None
        for encoding in ("cp1252", "latin-1"):
            try:
                next_value = candidate.encode(encoding).decode("utf-8")
                break
            except UnicodeError:
                continue
        if next_value is None:
            return None
        candidate = next_value
        if any("\u0600" <= char <= "\u06ff" for char in candidate):
            return candidate
    return None


def introduced(sample: str) -> str:
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%h %s", "-S", sample, "--", "."],
            text=True, capture_output=True, check=False,
        )
    except FileNotFoundError:
        return "git unavailable in scan runtime"
    return result.stdout.strip() or "untracked/unknown"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    rows: list[tuple[Path, list[tuple[str, str]]]] = []
    for root in ROOTS:
        for path in Path(root).rglob("*"):
            if path.suffix not in SUFFIXES or not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            found = [(line, fixed) for line in text.splitlines() if (fixed := repaired(line))]
            if found:
                rows.append((path, found))
    lines = ["# Mojibake inventory (read-only)", "", "| file | affected lines | sample | introduced by |", "|---|---:|---|---|"]
    for path, found in rows:
        sample, fixed = found[0]
        lines.append(f"| `{path}` | {len(found)} | `{sample[:80]}` → `{fixed[:80]}` | {introduced(sample[:80])} |")
    lines += ["", f"Affected files: {len(rows)}."]
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"files={len(rows)} report={args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
