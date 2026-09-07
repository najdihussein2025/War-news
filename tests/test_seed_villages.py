from __future__ import annotations

from types import SimpleNamespace

from app.core.seeds import seed_villages as seed_villages_module


class _ScalarsResult:
    def __init__(self, values):
        self._values = values

    def all(self):
        return self._values


class _StubSession:
    def __init__(self, existing_codes):
        self.existing_codes = existing_codes
        self.added = []
        self.committed = 0

    def scalars(self, stmt):
        return _ScalarsResult(self.existing_codes)

    def add(self, item):
        self.added.append(item)

    def commit(self):
        self.committed += 1


def test_load_villages_reads_configured_json_path(tmp_path, monkeypatch) -> None:
    villages_path = tmp_path / "Villages.json"
    villages_path.write_text(
        """
        [
          {
            "acs_code": 10110,
            "acs_name": "Aain el-Mraisse fonciere",
            "cad_name": "Ain el-Mreisse",
            "ref_name_en": "Ain el Mraisse",
            "ref_name_ar": "Ain el Mraisse AR",
            "caza_en": "Beirut",
            "caza_ar": "Beirut AR",
            "mohafaza_en": "Beirut",
            "mohafaza_ar": "Beirut AR",
            "coord_x": null,
            "coord_y": null
          }
        ]
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(seed_villages_module, "VILLAGES_JSON_PATH", villages_path)

    rows = seed_villages_module._load_villages()

    assert rows == [
        {
            "acs_code": 10110,
            "acs_name": "Aain el-Mraisse fonciere",
            "cad_name": "Ain el-Mreisse",
            "ref_name_en": "Ain el Mraisse",
            "ref_name_ar": "Ain el Mraisse AR",
            "caza_en": "Beirut",
            "caza_ar": "Beirut AR",
            "mohafaza_en": "Beirut",
            "mohafaza_ar": "Beirut AR",
            "coord_x": None,
            "coord_y": None,
        }
    ]


def test_seed_villages_skips_existing_rows_without_clearing_coordinates(
    monkeypatch,
) -> None:
    existing = SimpleNamespace(
        acs_code=10110,
        acs_name="old acs",
        cad_name="old cad",
        ref_name_en="old en",
        ref_name_ar="old ar",
        caza_en="old caza en",
        caza_ar="old caza ar",
        mohafaza_en="old moh en",
        mohafaza_ar="old moh ar",
        coord_x=123.45,
        coord_y=678.9,
    )
    session = _StubSession([existing.acs_code])

    monkeypatch.setattr(
        seed_villages_module,
        "_load_villages",
        lambda: [
            {
                "acs_code": 10110,
                "acs_name": "new acs",
                "cad_name": "new cad",
                "ref_name_en": "new en",
                "ref_name_ar": "new ar",
                "caza_en": "Beirut",
                "caza_ar": "Beirut AR",
                "mohafaza_en": "Beirut",
                "mohafaza_ar": "Beirut AR",
                "coord_x": None,
                "coord_y": None,
            }
        ],
    )

    inserted, skipped = seed_villages_module.seed_villages(session)

    assert (inserted, skipped) == (0, 1)
    assert existing.acs_name == "old acs"
    assert existing.ref_name_ar == "old ar"
    assert existing.coord_x == 123.45
    assert existing.coord_y == 678.9
    assert session.added == []
    assert session.committed == 1
