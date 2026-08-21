from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

POLL_SECONDS = 1.0
WATCH_EXTENSIONS = {".py", ".yml", ".yaml", ".json", ".toml", ".ini", ".env", ".txt"}
IGNORE_DIR_NAMES = {
    ".git",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
}


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a Python module and restart it when watched files change."
    )
    parser.add_argument("module", help="Python module path to run with -m.")
    parser.add_argument(
        "--root",
        action="append",
        dest="roots",
        help="Optional watch root. Defaults to /app/app and /app/.env when present.",
    )
    return parser.parse_args(argv)


def _default_roots() -> list[Path]:
    candidates = [Path("/app/app"), Path("/app/.env"), Path("/app/requirements.txt")]
    return [candidate for candidate in candidates if candidate.exists()]


def _iter_watch_files(root: Path):
    if root.is_file():
        yield root
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in IGNORE_DIR_NAMES]
        current_dir = Path(dirpath)
        for filename in filenames:
            path = current_dir / filename
            if path.suffix in WATCH_EXTENSIONS or path.name == ".env":
                yield path


def _snapshot(roots: list[Path]) -> dict[str, int]:
    snapshot: dict[str, int] = {}
    for root in roots:
        for path in _iter_watch_files(root):
            try:
                snapshot[str(path)] = path.stat().st_mtime_ns
            except FileNotFoundError:
                continue
    return snapshot


def _terminate_process(process: subprocess.Popen[bytes]) -> int:
    if process.poll() is not None:
        return int(process.returncode or 0)

    process.send_signal(signal.SIGTERM)
    try:
        return process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.wait(timeout=5)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    roots = [Path(root).resolve() for root in (args.roots or [])]
    if not roots:
        roots = _default_roots()
    if not roots:
        print("error: no watch roots found", file=sys.stderr)
        return 2

    command = [sys.executable, "-m", args.module]
    print(
        f"Reload runner starting module={args.module} "
        f"roots={[str(root) for root in roots]}",
        flush=True,
    )

    snapshot = _snapshot(roots)
    process = subprocess.Popen(command)

    try:
        while True:
            time.sleep(POLL_SECONDS)
            current = _snapshot(roots)
            if current != snapshot:
                print(
                    f"Reload runner detected file changes; restarting module={args.module}",
                    flush=True,
                )
                _terminate_process(process)
                snapshot = current
                process = subprocess.Popen(command)
                continue

            returncode = process.poll()
            if returncode is not None:
                return int(returncode)
    except KeyboardInterrupt:
        return _terminate_process(process)
    finally:
        if process.poll() is None:
            _terminate_process(process)


if __name__ == "__main__":
    raise SystemExit(main())
