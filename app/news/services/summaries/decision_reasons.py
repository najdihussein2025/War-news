"""Central, append-only administrator-facing summary decision notes."""
from __future__ import annotations

from pathlib import Path
import yaml

_PATH = Path(__file__).with_name("decision_reasons.yaml")


def definitions() -> dict[str, dict[str, str]]:
    return yaml.safe_load(_PATH.read_text(encoding="utf-8")) or {}


def label(code: str) -> str:
    return definitions()[code]["label"]


def note(code: str, **values: object) -> str:
    template = definitions()[code]["template"]
    safe = {key: "" if value is None else str(value) for key, value in values.items()}
    return template.format_map(safe).replace(". ", ". ").replace("..", ".")


def append_note(existing: str | None, value: str) -> str:
    """Keep decisions auditable and make repeated confirmation writes idempotent."""
    if not existing or value in existing:
        return existing or value
    return f"{existing}\n\n{value}"
