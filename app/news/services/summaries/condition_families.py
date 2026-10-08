"""Condition families for summary reconciliation (data lives in condition_families.yaml)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

import yaml

FAMILIES_PATH = Path(__file__).with_name("condition_families.yaml")


def load_family_names(path: Path = FAMILIES_PATH) -> dict[str, tuple[str, ...]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {name: tuple(members) for name, members in (data.get("families") or {}).items()}


@dataclass(frozen=True)
class ConditionFamilies:
    """Maps a condition id to every id it may match (itself plus its family)."""

    _equivalents: Mapping[int, frozenset[int]]

    @classmethod
    def from_names(
        cls,
        families: Mapping[str, Iterable[str]],
        id_by_action_en: Mapping[str, int],
    ) -> "ConditionFamilies":
        equivalents: dict[int, set[int]] = {}
        for members in families.values():
            ids = {id_by_action_en[name] for name in members if name in id_by_action_en}
            for condition_id in ids:
                equivalents.setdefault(condition_id, set()).update(ids)
        return cls({key: frozenset(value) for key, value in equivalents.items()})

    def equivalents(self, condition_id: int) -> frozenset[int]:
        return self._equivalents.get(condition_id, frozenset({condition_id})) | {condition_id}

    def same(self, left: int | None, right: int | None) -> bool:
        if left is None or right is None:
            return False
        return left == right or right in self.equivalents(left)


def load_condition_families(session) -> ConditionFamilies:
    """Resolve the YAML names against the connected database's conditions table."""
    from sqlalchemy import select

    from app.news.models import Condition

    rows = session.execute(select(Condition.id, Condition.action_en)).all()
    return ConditionFamilies.from_names(load_family_names(), {name: cid for cid, name in rows})
