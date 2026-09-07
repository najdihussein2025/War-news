from __future__ import annotations

from types import SimpleNamespace

from app.core.seeds import seed_village_location_aliases as seed_module
from app.core.text_normalization import normalize_arabic_text
from app.news.services.matching.matching_service import MatchingService
from app.news.services.matching.village_aliases import (
    PROPOSED_VILLAGE_LOCATION_ALIASES,
)


class _ScalarsResult:
    def __init__(self, values):
        self._values = values

    def all(self):
        return self._values


class _ExecuteResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _StubSession:
    def __init__(self, *, existing_norms=(), villages_by_acs=None):
        self.existing_norms = list(existing_norms)
        self.villages_by_acs = villages_by_acs or {71111: 1152, 71113: 1153}
        self.added = []
        self.committed = 0

    def scalars(self, stmt):
        return _ScalarsResult(self.existing_norms)

    def execute(self, stmt):
        return _ExecuteResult(list(self.villages_by_acs.items()))

    def add(self, item):
        self.added.append(item)

    def commit(self):
        self.committed += 1


def test_proposed_aliases_cover_maslakh_recon_mentions() -> None:
    texts = {row.alias_text for row in PROPOSED_VILLAGE_LOCATION_ALIASES}
    assert "النبطية" in texts
    assert "مدينة النبطية" in texts
    assert "حي المسلخ" in texts
    assert "المسلخ" in texts
    assert all(row.confidence == "proposed" for row in PROPOSED_VILLAGE_LOCATION_ALIASES)


def test_seed_village_location_aliases_inserts_new_rows(monkeypatch, tmp_path) -> None:
    path = tmp_path / "aliases.json"
    path.write_text(
        """
        [
          {
            "alias_text": "النبطية",
            "parent_acs_code": 71111,
            "note": "city seat"
          }
        ]
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(seed_module, "VILLAGE_LOCATION_ALIASES_JSON_PATH", path)
    session = _StubSession()

    inserted, skipped, missing = seed_module.seed_village_location_aliases(session)

    assert inserted == 1
    assert skipped == 0
    assert missing == 0
    assert session.committed == 1
    alias = session.added[0]
    assert alias.alias_text == "النبطية"
    assert alias.alias_normalized == normalize_arabic_text("النبطية")
    assert alias.village_id == 1152


def test_seed_skips_when_parent_acs_missing(monkeypatch, tmp_path) -> None:
    path = tmp_path / "aliases.json"
    path.write_text(
        '[{"alias_text": "النبطية", "parent_acs_code": 999999, "note": "x"}]',
        encoding="utf-8",
    )
    monkeypatch.setattr(seed_module, "VILLAGE_LOCATION_ALIASES_JSON_PATH", path)
    session = _StubSession(villages_by_acs={71111: 1152})

    inserted, skipped, missing = seed_module.seed_village_location_aliases(session)

    assert inserted == 0
    assert missing == 1
    assert skipped == 0


class _AliasVillageRepo:
    def __init__(self, alias_map: dict[str, tuple[int, float]]):
        self.alias_map = alias_map
        self.similar_calls: list[str] = []

    def resolve_alias(self, normalized_text: str):
        hit = self.alias_map.get(normalized_text)
        if hit is None:
            return None
        village_id, score = hit
        return SimpleNamespace(id=village_id), score

    def find_similar(self, text: str, limit: int = 5):
        self.similar_calls.append(text)
        # Would wrongly win without alias: Douair-style
        return [(SimpleNamespace(id=543), 0.615)]


class _EmptyConditionRepo:
    def find_similar(self, text: str, limit: int = 5):
        return []


def test_matching_service_prefers_alias_over_fuzzy_douair() -> None:
    from datetime import datetime, timezone

    from app.llm.dtos import ExtractionResult

    villages = _AliasVillageRepo(
        {normalize_arabic_text("النبطية"): (1152, 1.0)}
    )
    service = MatchingService(villages, _EmptyConditionRepo())
    result = service.match(
        ExtractionResult(
            is_relevant=True,
            village=["النبطية"],
            village_roles=[],
            action_description=None,
            model="test",
            extracted_at=datetime.now(timezone.utc),
        )
    )
    assert result.village_matches[0].matched_village_id == 1152
    assert result.village_matches[0].village_confidence == 1.0
    assert result.village_matches[0].village_match_status.value == "matched"
    assert villages.similar_calls == []
